"""Classificação geométrica e estabilidade temporal dos gestos."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


GESTOS_DISCRETOS = {"peace", "three_fingers", "thumb_pinky", "four_fingers"}


def _angulo(a: Any, centro: Any, b: Any) -> float:
    primeiro = (a.x - centro.x, a.y - centro.y, a.z - centro.z)
    segundo = (b.x - centro.x, b.y - centro.y, b.z - centro.z)
    norma = math.sqrt(sum(v * v for v in primeiro)) * math.sqrt(sum(v * v for v in segundo))
    if norma == 0:
        return 0.0
    cosseno = max(-1.0, min(1.0, sum(x * y for x, y in zip(primeiro, segundo)) / norma))
    return math.degrees(math.acos(cosseno))


def estados_dedos(mao: Any) -> tuple[bool, bool, bool, bool, bool]:
    """Retorna polegar, indicador, médio, anelar e mínimo estendidos."""
    pontos = mao.landmark
    polegar = _angulo(pontos[2], pontos[3], pontos[4]) >= 150
    dedos = tuple(
        _angulo(pontos[mcp], pontos[pip], pontos[tip]) >= 155
        for mcp, pip, tip in ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))
    )
    return (polegar, *dedos)


def classificar_gesto(mao: Any) -> str | None:
    """Classifica padrões com prioridade para evitar conflitos."""
    polegar, indicador, medio, anelar, minimo = estados_dedos(mao)
    if (polegar, indicador, medio, anelar, minimo) == (True, True, True, True, True):
        return "open_palm"
    if indicador and medio and anelar and not minimo:
        return "three_fingers"
    if indicador and medio and not anelar and not minimo:
        return "peace"
    if polegar and not indicador and not medio and not anelar and minimo:
        return "thumb_pinky"
    if not polegar and indicador and medio and anelar and minimo:
        return "four_fingers"
    if indicador and not medio and not anelar and not minimo:
        return "pinch"
    return None


def selecionar_mao(resultado: Any, mao_controle: str) -> Any | None:
    maos = getattr(resultado, "multi_hand_landmarks", None) or []
    if mao_controle == "any":
        return maos[0] if maos else None
    lateralidades = getattr(resultado, "multi_handedness", None) or []
    for mao, lateralidade in zip(maos, lateralidades):
        classificacoes = getattr(lateralidade, "classification", None) or []
        if classificacoes and classificacoes[0].label.lower() == mao_controle:
            return mao
    return None


def lateralidade_mao(resultado: Any, mao_selecionada: Any) -> str | None:
    maos = getattr(resultado, "multi_hand_landmarks", None) or []
    lateralidades = getattr(resultado, "multi_handedness", None) or []
    for mao, lateralidade in zip(maos, lateralidades):
        if mao is mao_selecionada and lateralidade.classification:
            return lateralidade.classification[0].label.lower()
    return None


@dataclass(frozen=True)
class EstadoGesto:
    candidato: str | None = None
    confirmado: str | None = None
    acao: str | None = None
    progresso: float = 0.0
    fase: str = "neutro"


class MotorGestos:
    def __init__(
        self,
        mapeamento: dict[str, str],
        estabilidade: float,
        liberacao: float,
        cooldown_padrao: float,
        cooldowns: dict[str, float],
        tolerancia_perda: float = 0.0,
    ) -> None:
        self.mapeamento = mapeamento
        self.estabilidade = estabilidade
        self.liberacao = liberacao
        self.cooldown_padrao = cooldown_padrao
        self.cooldowns = cooldowns
        self.tolerancia_perda = tolerancia_perda
        self._candidato: str | None = None
        self._desde = 0.0
        self._bloqueado: str | None = None
        self._liberando_desde: float | None = None
        self._ultima_acao: dict[str, float] = {}
        self._perdido_desde: float | None = None

    def atualizar(self, gesto: str | None, ativo: bool, agora: float) -> EstadoGesto:
        if self._bloqueado is not None:
            if gesto == self._bloqueado:
                self._liberando_desde = None
            elif self._liberando_desde is None:
                self._liberando_desde = agora
            elif agora - self._liberando_desde >= self.liberacao:
                self._bloqueado = None
                self._liberando_desde = None

        if not ativo:
            self._candidato = None
            return EstadoGesto()
        if gesto is None and self._candidato is not None:
            if self._perdido_desde is None:
                self._perdido_desde = agora
            if agora - self._perdido_desde <= self.tolerancia_perda:
                progresso = 1.0 if self.estabilidade == 0 else min(1.0, (self._perdido_desde - self._desde) / self.estabilidade)
                return EstadoGesto(candidato=self._candidato, progresso=progresso, fase="candidato")
            self._candidato = None
        elif gesto == self._candidato and self._perdido_desde is not None:
            self._desde += agora - self._perdido_desde
            self._perdido_desde = None
        elif gesto != self._candidato:
            self._perdido_desde = None
        if gesto not in GESTOS_DISCRETOS:
            self._candidato = None
            return EstadoGesto()
        acao = self.mapeamento.get(gesto, "")
        if not acao:
            self._candidato = None
            return EstadoGesto(candidato=gesto, fase="candidato")
        if gesto != self._candidato:
            self._candidato = gesto
            self._desde = agora
        decorrido = agora - self._desde
        progresso = 1.0 if self.estabilidade == 0 else min(1.0, decorrido / self.estabilidade)
        if progresso < 1.0 or self._bloqueado == gesto:
            fase = "aguardando_liberacao" if self._bloqueado == gesto else "candidato"
            return EstadoGesto(candidato=gesto, progresso=progresso, fase=fase)
        cooldown = self.cooldowns.get(acao, self.cooldown_padrao)
        if agora - self._ultima_acao.get(acao, float("-inf")) < cooldown:
            return EstadoGesto(candidato=gesto, progresso=1.0, fase="cooldown")
        self._ultima_acao[acao] = agora
        self._bloqueado = gesto
        return EstadoGesto(candidato=gesto, confirmado=gesto, acao=acao, progresso=1.0, fase="confirmado")


class ControleAtivacao:
    def __init__(self, habilitado: bool, espera: float, cooldown: float, iniciar_ativo: bool) -> None:
        self.habilitado = habilitado
        self.espera = espera
        self.cooldown = cooldown
        self.ativo = iniciar_ativo if habilitado else True
        self._inicio: float | None = None
        self._liberada = True
        self._ultima = float("-inf")

    def atualizar(self, palma_aberta: bool, agora: float) -> bool:
        if not self.habilitado:
            return False
        if not palma_aberta:
            self._inicio = None
            self._liberada = True
            return False
        if not self._liberada:
            return False
        if self._inicio is None:
            self._inicio = agora
            return False
        if agora - self._inicio >= self.espera and agora - self._ultima >= self.cooldown:
            self.ativo = not self.ativo
            self._ultima = agora
            self._liberada = False
            return True
        return False

    def progresso(self, agora: float) -> float:
        if self._inicio is None or self.espera == 0:
            return 0.0 if self._inicio is None else 1.0
        return min(1.0, max(0.0, (agora - self._inicio) / self.espera))


def processar_estado_gesto(
    gesto: str | None,
    agora: float,
    ativacao: ControleAtivacao,
    motor: MotorGestos,
) -> tuple[bool, EstadoGesto]:
    """Dá prioridade exclusiva à palma e bloqueia ações quando inativo."""
    palma = gesto == "open_palm"
    alternou = ativacao.atualizar(palma, agora)
    estado = motor.atualizar(None if palma else gesto, ativacao.ativo, agora)
    return alternou, estado
