"""Fila, worker e comandos externos permitidos pelo GestureDeck."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
from typing import Callable
import wave


COMANDOS: dict[str, list[str]] = {
    "play_pause": ["playerctl", "play-pause"],
    "next_track": ["playerctl", "next"],
    "previous_track": ["playerctl", "previous"],
    "mute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
}


@dataclass(frozen=True)
class Comando:
    acao: str
    valor: float | str | None = None


@dataclass(frozen=True)
class ResultadoAcao:
    acao: str
    sucesso: bool
    mensagem: str


class FilaAcoes:
    """Mantém no máximo um item pendente por ação."""

    def __init__(self) -> None:
        self._itens: OrderedDict[str, Comando] = OrderedDict()
        self._condicao = threading.Condition()
        self._fechada = False

    def adicionar(self, comando: Comando) -> None:
        with self._condicao:
            if self._fechada:
                return
            self._itens[comando.acao] = comando
            self._itens.move_to_end(comando.acao)
            self._condicao.notify()

    def obter(self, timeout: float = 0.1) -> Comando | None:
        with self._condicao:
            if not self._itens and not self._fechada:
                self._condicao.wait(timeout)
            if self._fechada:
                return None
            if not self._itens:
                return None
            _, comando = self._itens.popitem(last=False)
            return comando

    def fechar(self) -> None:
        with self._condicao:
            self._fechada = True
            self._itens.clear()
            self._condicao.notify_all()

    def __len__(self) -> int:
        with self._condicao:
            return len(self._itens)

    @property
    def fechada(self) -> bool:
        with self._condicao:
            return self._fechada


class ExecutorAcoes:
    def __init__(
        self,
        executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        localizar: Callable[[str], str | None] = shutil.which,
        avisar: Callable[[str], None] = print,
    ) -> None:
        self._executar = executar
        self._disponivel = {nome: localizar(nome) is not None for nome in ("wpctl", "playerctl", "pw-play")}
        self._avisar = avisar
        self._avisados: set[str] = set()

    def verificar_dependencias(self) -> None:
        for programa in ("wpctl", "playerctl", "pw-play"):
            if not self._disponivel[programa]:
                self._avisar_uma_vez(programa)

    def _avisar_uma_vez(self, programa: str) -> None:
        if programa in self._avisados:
            return
        efeitos = {
            "wpctl": "volume e mute ficam indisponíveis",
            "playerctl": "ações de mídia ficam desativadas",
            "pw-play": "avisos sonoros ficam desativados",
        }
        self._avisar(f"Aviso: {programa} não foi encontrado; {efeitos[programa]}.")
        self._avisados.add(programa)

    def executar(self, comando: Comando) -> ResultadoAcao:
        if comando.acao == "volume":
            argumentos = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{float(comando.valor):.2f}"]
            programa = "wpctl"
        elif comando.acao in COMANDOS:
            argumentos = COMANDOS[comando.acao]
            programa = argumentos[0]
        else:
            return ResultadoAcao(comando.acao, False, "ação não reconhecida")
        if not self._disponivel[programa]:
            self._avisar_uma_vez(programa)
            return ResultadoAcao(comando.acao, False, f"{programa} indisponível")
        try:
            self._executar(
                argumentos,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError) as erro:
            return ResultadoAcao(comando.acao, False, str(erro))
        return ResultadoAcao(comando.acao, True, "executada")

    def beep(self, tipo: str) -> None:
        if not self._disponivel["pw-play"]:
            self._avisar_uma_vez("pw-play")
            return
        frequencias = {"activate": 880, "deactivate": 330, "confirm": 660}
        frequencia = frequencias[tipo]
        caminho: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporario:
                caminho = Path(temporario.name)
            taxa, duracao = 44_100, 0.10 if tipo == "confirm" else 0.14
            total = int(taxa * duracao)
            with wave.open(str(caminho), "wb") as audio:
                audio.setparams((1, 2, taxa, total, "NONE", "not compressed"))
                audio.writeframes(b"".join(
                    struct.pack("<h", int(12_000 * math.sin(2 * math.pi * frequencia * i / taxa)))
                    for i in range(total)
                ))
            self._executar(
                ["pw-play", str(caminho)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if caminho is not None:
                caminho.unlink(missing_ok=True)


class WorkerAcoes:
    def __init__(self, executor: ExecutorAcoes, beep: bool = True) -> None:
        self.fila = FilaAcoes()
        self.resultados: list[ResultadoAcao] = []
        self._executor = executor
        self._beep = beep
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._processar, name="actions-worker")

    def iniciar(self) -> None:
        self._thread.start()

    def adicionar(self, acao: str, valor: float | str | None = None) -> None:
        self.fila.adicionar(Comando(acao, valor))

    def coletar_resultados(self) -> list[ResultadoAcao]:
        with self._lock:
            resultados, self.resultados = self.resultados, []
            return resultados

    def encerrar(self) -> None:
        self.fila.fechar()
        if self._thread.is_alive():
            self._thread.join()

    @property
    def ativo(self) -> bool:
        return self._thread.is_alive()

    def _processar(self) -> None:
        while True:
            comando = self.fila.obter()
            if comando is None:
                if self.fila.fechada:
                    return
                continue
            if comando.acao == "beep":
                self._executor.beep(str(comando.valor))
                continue
            resultado = self._executor.executar(comando)
            with self._lock:
                self.resultados.append(resultado)
            if resultado.sucesso and self._beep and comando.acao not in {"volume"}:
                self._executor.beep("confirm")


class LimitadorVolume:
    def __init__(self, intervalo: float, mudanca_minima: float) -> None:
        self.intervalo = intervalo
        self.mudanca_minima = mudanca_minima
        self._ultimo_volume = -1.0
        self._ultimo_instante = float("-inf")

    def aceitar(self, volume: float, agora: float) -> bool:
        if agora - self._ultimo_instante < self.intervalo:
            return False
        if abs(volume - self._ultimo_volume) < self.mudanca_minima:
            return False
        self._ultimo_volume = volume
        self._ultimo_instante = agora
        return True
