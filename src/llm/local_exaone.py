"""Singleton loader for the local instruction-tuned LLM (Exaone 3.5 7.8B by default).

Model id and quantization mode come from `config/settings.yaml` (llm.local_model,
llm.quantization). The loaded pipeline is reused across translate/tag/preprocess
calls — never reload per article.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

import torch

from src.config.loader import get_settings


@dataclass
class _Loaded:
    tokenizer: object
    model: object
    device: str


_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], _Loaded] = {}


def _build_quant_config(quantization: str):
    from transformers import BitsAndBytesConfig

    if quantization == "4bit":
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
    return None  # fp16 path — no quant config


def load() -> _Loaded:
    """Load (or reuse) the local LLM as configured in settings.yaml."""
    settings = get_settings()
    model_id = settings.llm.local_model
    quant = settings.llm.quantization
    key = (model_id, quant)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        kwargs: dict = {"trust_remote_code": True}
        quant_config = _build_quant_config(quant)
        if quant_config is not None:
            kwargs["quantization_config"] = quant_config
            kwargs["device_map"] = "auto"
        else:
            kwargs["torch_dtype"] = torch.float16
            kwargs["device_map"] = "auto" if torch.cuda.is_available() else None

        model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
        model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        loaded = _Loaded(tokenizer=tokenizer, model=model, device=device)
        _CACHE[key] = loaded
        return loaded


def generate(
    user: str,
    *,
    system: Optional[str] = None,
    max_new_tokens: int = 512,
    temperature: float = 0.1,
    stop: Optional[list[str]] = None,
) -> str:
    """Single-turn chat generation. Returns only the newly generated text."""
    loaded = load()
    tokenizer = loaded.tokenizer
    model = loaded.model

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    # Render → tokenize in two steps. Some chat templates return a dict-like
    # `BatchEncoding` when `return_tensors="pt"` is passed directly, which
    # trips up `model.generate` — going through plain-text avoids that.
    prompt_text = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=False,
    )
    enc = tokenizer(prompt_text, return_tensors="pt").to(model.device)
    input_ids = enc.input_ids
    attention_mask = enc.attention_mask

    gen_kwargs = {
        "max_new_tokens": max_new_tokens,
        "do_sample": temperature > 0,
        "pad_token_id": tokenizer.eos_token_id,
        "attention_mask": attention_mask,
    }
    if temperature > 0:
        gen_kwargs["temperature"] = temperature

    with torch.inference_mode():
        output_ids = model.generate(input_ids, **gen_kwargs)

    new_tokens = output_ids[0, input_ids.shape[1]:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    if stop:
        for s in stop:
            idx = text.find(s)
            if idx != -1:
                text = text[:idx].rstrip()
                break
    return text
