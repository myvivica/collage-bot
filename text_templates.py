"""Шаблоны текстовых буллетов для инфографики.

Встроенные шаблоны живут в коде (переживают редеплой Railway),
пользовательские — в bot_data персистентности бота.
"""

from __future__ import annotations

BUILTIN: dict[str, list[str]] = {
    "Хлопок · кружево": [
        "Комфортно носить весь день",
        "Ластовица 100% хлопок",
        "Кружево тянется",
    ],
}

CUSTOM_KEY = "info_text_templates"


def all_templates(bot_data: dict) -> dict[str, list[str]]:
    merged = dict(BUILTIN)
    merged.update(bot_data.get(CUSTOM_KEY, {}))
    return merged


def save_template(bot_data: dict, name: str, lines: list[str]) -> None:
    bot_data.setdefault(CUSTOM_KEY, {})[name] = lines


def delete_template(bot_data: dict, name: str) -> bool:
    return bot_data.get(CUSTOM_KEY, {}).pop(name, None) is not None
