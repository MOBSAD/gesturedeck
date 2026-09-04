"""Carregamento e validação da configuração TOML."""

from __future__ import annotations

import copy
import math
from pathlib import Path
import tomllib
from typing import Any


ACOES_SEGURAS = {"", "volume", "play_pause", "next_track", "previous_track", "mute"}

CONFIGURACAO_PADRAO: dict[str, dict[str, Any]] = {
    "interface": {"visible": True},
    "camera": {"device": 0, "width": 640, "height": 480, "fps": 30},
    "tracking": {
        "process_every_n_frames": 2,
        "detection_confidence": 0.65,
        "tracking_confidence": 0.65,
        "control_hand": "any",
    },
    "volume": {
        "minimum_distance": 25.0,
        "maximum_distance": 180.0,
        "smoothing": 0.18,
        "update_interval": 0.15,
        "minimum_change": 0.03,
    },
    "activation": {
        "enabled": True,
        "hold_seconds": 0.8,
        "cooldown": 1.5,
        "start_active": False,
        "beep": True,
    },
    "gestures": {
        "pinch": "volume",
        "fist": "play_pause",
        "peace": "next_track",
        "three_fingers": "previous_track",
        "thumb_pinky": "mute",
    },
    "gesture_detection": {
        "stability_seconds": 0.35,
        "release_seconds": 0.25,
        "default_cooldown": 1.0,
    },
    "gesture_cooldowns": {
        "play_pause": 1.0,
        "next_track": 1.0,
        "previous_track": 1.0,
        "mute": 1.0,
    },
}


class ErroConfiguracao(ValueError):
    """Indica uma opção inválida no arquivo de configuração."""


def _validar_inteiro(valor: Any, nome: str, minimo: int = 0) -> None:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroConfiguracao(f"'{nome}' deve ser um número inteiro.")
    if valor < minimo:
        raise ErroConfiguracao(f"'{nome}' deve ser maior ou igual a {minimo}.")


def _validar_numero(
    valor: Any, nome: str, minimo: float = 0.0, maximo: float | None = None
) -> None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErroConfiguracao(f"'{nome}' deve ser um número.")
    if not math.isfinite(valor) or valor < minimo or (maximo is not None and valor > maximo):
        intervalo = f"entre {minimo} e {maximo}" if maximo is not None else f"maior ou igual a {minimo}"
        raise ErroConfiguracao(f"'{nome}' deve ser {intervalo}.")


def carregar_configuracao(caminho: str | Path = "config.toml") -> dict[str, dict[str, Any]]:
    configuracao = copy.deepcopy(CONFIGURACAO_PADRAO)
    caminho = Path(caminho)
    if caminho.exists():
        try:
            with caminho.open("rb") as arquivo:
                dados = tomllib.load(arquivo)
        except (OSError, tomllib.TOMLDecodeError) as erro:
            raise ErroConfiguracao(f"Não foi possível ler '{caminho}': {erro}") from erro
        for secao, valores in dados.items():
            if secao not in configuracao:
                continue
            if not isinstance(valores, dict):
                raise ErroConfiguracao(f"A seção '{secao}' deve ser uma tabela TOML.")
            for opcao, valor in valores.items():
                if opcao in configuracao[secao]:
                    configuracao[secao][opcao] = valor

    if not isinstance(configuracao["interface"]["visible"], bool):
        raise ErroConfiguracao("'interface.visible' deve ser true ou false.")
    for opcao in ("device", "width", "height", "fps"):
        _validar_inteiro(configuracao["camera"][opcao], f"camera.{opcao}", 0 if opcao == "device" else 1)
    _validar_inteiro(configuracao["tracking"]["process_every_n_frames"], "tracking.process_every_n_frames", 1)
    for opcao in ("detection_confidence", "tracking_confidence"):
        _validar_numero(configuracao["tracking"][opcao], f"tracking.{opcao}", 0.0, 1.0)
    mao_controle = configuracao["tracking"]["control_hand"]
    if not isinstance(mao_controle, str) or mao_controle not in {"left", "right", "any"}:
        raise ErroConfiguracao("'tracking.control_hand' deve ser 'left', 'right' ou 'any'.")

    for opcao in ("minimum_distance", "maximum_distance", "update_interval", "minimum_change"):
        _validar_numero(configuracao["volume"][opcao], f"volume.{opcao}")
    _validar_numero(configuracao["volume"]["smoothing"], "volume.smoothing", 0.0, 1.0)
    if configuracao["volume"]["maximum_distance"] <= configuracao["volume"]["minimum_distance"]:
        raise ErroConfiguracao("'volume.maximum_distance' deve ser maior que 'volume.minimum_distance'.")
    if configuracao["volume"]["minimum_change"] > 1:
        raise ErroConfiguracao("'volume.minimum_change' deve estar entre 0.0 e 1.0.")

    for opcao in ("enabled", "start_active", "beep"):
        if not isinstance(configuracao["activation"][opcao], bool):
            raise ErroConfiguracao(f"'activation.{opcao}' deve ser true ou false.")
    for opcao in ("hold_seconds", "cooldown"):
        _validar_numero(configuracao["activation"][opcao], f"activation.{opcao}")

    for gesto, acao in configuracao["gestures"].items():
        if not isinstance(acao, str) or acao not in ACOES_SEGURAS:
            permitidas = ", ".join(repr(item) for item in sorted(ACOES_SEGURAS))
            raise ErroConfiguracao(f"'gestures.{gesto}' deve ser uma ação reconhecida: {permitidas}.")
        if gesto == "pinch" and acao not in {"", "volume"}:
            raise ErroConfiguracao("'gestures.pinch' aceita somente 'volume' ou string vazia.")
        if gesto != "pinch" and acao == "volume":
            raise ErroConfiguracao(f"'gestures.{gesto}' não pode usar a ação contínua 'volume'.")
    for opcao in ("stability_seconds", "release_seconds", "default_cooldown"):
        _validar_numero(configuracao["gesture_detection"][opcao], f"gesture_detection.{opcao}")
    for acao, cooldown in configuracao["gesture_cooldowns"].items():
        _validar_numero(cooldown, f"gesture_cooldowns.{acao}")
    return configuracao
