"""Controle de volume por gestos usando uma webcam."""

from __future__ import annotations

import copy
import math
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import tomllib
from typing import Any
import wave


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
}

_AVISO_PW_PLAY_EXIBIDO = False


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
    """Lê, completa e valida a configuração do GestureDeck."""
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

    visible = configuracao["interface"]["visible"]
    if not isinstance(visible, bool):
        raise ErroConfiguracao("'interface.visible' deve ser true ou false.")

    for opcao in ("device", "width", "height", "fps"):
        minimo = 0 if opcao == "device" else 1
        _validar_inteiro(configuracao["camera"][opcao], f"camera.{opcao}", minimo)

    _validar_inteiro(
        configuracao["tracking"]["process_every_n_frames"],
        "tracking.process_every_n_frames",
        1,
    )
    for opcao in ("detection_confidence", "tracking_confidence"):
        _validar_numero(configuracao["tracking"][opcao], f"tracking.{opcao}", 0.0, 1.0)
    mao_controle = configuracao["tracking"]["control_hand"]
    if not isinstance(mao_controle, str) or mao_controle not in {"left", "right", "any"}:
        raise ErroConfiguracao(
            "'tracking.control_hand' deve ser 'left', 'right' ou 'any'."
        )

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
    _validar_numero(
        configuracao["activation"]["hold_seconds"],
        "activation.hold_seconds",
    )
    _validar_numero(configuracao["activation"]["cooldown"], "activation.cooldown")

    return configuracao


def limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(valor, maximo))


def converter_distancia_em_volume(
    distancia: float, distancia_minima: float, distancia_maxima: float
) -> float:
    proporcao = (distancia - distancia_minima) / (distancia_maxima - distancia_minima)
    return limitar(proporcao, 0.0, 1.0)


def suavizar_volume(atual: float, alvo: float, fator: float) -> float:
    fator = limitar(fator, 0.0, 1.0)
    return limitar(atual + (alvo - atual) * fator, 0.0, 1.0)


def selecionar_mao(resultado: Any, mao_controle: str) -> Any | None:
    """Retorna a primeira mão que corresponde à lateralidade configurada."""
    maos = getattr(resultado, "multi_hand_landmarks", None) or []
    if mao_controle == "any":
        return maos[0] if maos else None

    lateralidades = getattr(resultado, "multi_handedness", None) or []
    for mao, lateralidade in zip(maos, lateralidades):
        classificacoes = getattr(lateralidade, "classification", None) or []
        if classificacoes and classificacoes[0].label.lower() == mao_controle:
            return mao
    return None


def _distancia_landmarks(a: Any, b: Any) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def palma_aberta(mao: Any) -> bool:
    """Reconhece uma palma quando as cinco pontas estão afastadas do pulso."""
    pulso = mao.landmark[0]
    pontas = (4, 8, 12, 16, 20)
    articulacoes = (3, 6, 10, 14, 18)
    return all(
        _distancia_landmarks(pulso, mao.landmark[ponta])
        > _distancia_landmarks(pulso, mao.landmark[articulacao]) * 1.15
        for ponta, articulacao in zip(pontas, articulacoes)
    )


class ControleAtivacao:
    """Alterna o controle após uma palma sustentada, com trava e cooldown."""

    def __init__(
        self, habilitado: bool, espera: float, cooldown: float, iniciar_ativo: bool
    ) -> None:
        self.habilitado = habilitado
        self.espera = espera
        self.cooldown = cooldown
        self.ativo = iniciar_ativo if habilitado else True
        self._inicio_palma: float | None = None
        self._palma_liberada = True
        self._ultima_alternancia = float("-inf")

    def atualizar(self, aberta: bool, agora: float) -> bool:
        """Atualiza o estado e informa se houve uma alternância."""
        if not self.habilitado:
            return False
        if not aberta:
            self._inicio_palma = None
            self._palma_liberada = True
            return False
        if not self._palma_liberada:
            return False
        if self._inicio_palma is None:
            self._inicio_palma = agora
            return False
        if (
            agora - self._inicio_palma >= self.espera
            and agora - self._ultima_alternancia >= self.cooldown
        ):
            self.ativo = not self.ativo
            self._ultima_alternancia = agora
            self._palma_liberada = False
            return True
        return False


def _reproduzir_beep(frequencia: int) -> None:
    caminho: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporario:
            caminho = Path(temporario.name)
        taxa = 44_100
        duracao = 0.14
        total = int(taxa * duracao)
        with wave.open(str(caminho), "wb") as audio:
            audio.setparams((1, 2, taxa, total, "NONE", "not compressed"))
            amostras = (
                struct.pack("<h", int(12_000 * math.sin(2 * math.pi * frequencia * i / taxa)))
                for i in range(total)
            )
            audio.writeframes(b"".join(amostras))
        subprocess.run(
            ["pw-play", str(caminho)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        if caminho is not None:
            caminho.unlink(missing_ok=True)


def tocar_beep(ativo: bool) -> None:
    """Agenda um aviso agudo ao ativar e grave ao desativar."""
    global _AVISO_PW_PLAY_EXIBIDO
    if shutil.which("pw-play") is None:
        if not _AVISO_PW_PLAY_EXIBIDO:
            print("Aviso: pw-play não foi encontrado; os avisos sonoros foram desativados.")
            _AVISO_PW_PLAY_EXIBIDO = True
        return
    threading.Thread(
        target=_reproduzir_beep,
        args=(880 if ativo else 330,),
        name="beep-worker",
        daemon=True,
    ).start()


def definir_volume(volume: float) -> None:
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{limitar(volume, 0.0, 1.0):.2f}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except FileNotFoundError as erro:
        raise RuntimeError("wpctl não foi encontrado no sistema.") from erro
    except subprocess.CalledProcessError as erro:
        raise RuntimeError("wpctl não conseguiu alterar o volume.") from erro
    except subprocess.TimeoutExpired as erro:
        raise RuntimeError("wpctl não respondeu a tempo.") from erro


def enfileirar_volume(fila: queue.Queue[float], volume: float) -> None:
    while True:
        try:
            fila.put_nowait(volume)
            return
        except queue.Full:
            try:
                fila.get_nowait()
            except queue.Empty:
                pass


def _obter_volume_mais_recente(fila: queue.Queue[float], primeiro: float) -> float:
    volume = primeiro
    while True:
        try:
            volume = fila.get_nowait()
        except queue.Empty:
            return volume


def processar_volumes(
    fila: queue.Queue[float],
    encerrar: threading.Event,
    intervalo: float,
    mudanca_minima: float,
) -> None:
    ultimo_volume = -1.0
    ultimo_comando = 0.0
    while not encerrar.is_set():
        try:
            volume = fila.get(timeout=0.05)
        except queue.Empty:
            continue
        volume = _obter_volume_mais_recente(fila, volume)
        espera = intervalo - (time.monotonic() - ultimo_comando)
        if espera > 0 and encerrar.wait(espera):
            break
        volume = _obter_volume_mais_recente(fila, volume)
        if abs(volume - ultimo_volume) < mudanca_minima:
            continue
        ultimo_comando = time.monotonic()
        try:
            definir_volume(volume)
        except RuntimeError as erro:
            print(f"Erro: {erro}")
        else:
            ultimo_volume = volume


def executar(configuracao: dict[str, dict[str, Any]]) -> None:
    import cv2
    import mediapipe as mp

    camera_cfg = configuracao["camera"]
    tracking_cfg = configuracao["tracking"]
    volume_cfg = configuracao["volume"]
    activation_cfg = configuracao["activation"]
    interface_visivel = configuracao["interface"]["visible"]
    ativacao = ControleAtivacao(
        activation_cfg["enabled"],
        activation_cfg["hold_seconds"],
        activation_cfg["cooldown"],
        activation_cfg["start_active"],
    )
    camera = None
    encerrar_worker = threading.Event()
    fila_volumes: queue.Queue[float] = queue.Queue(maxsize=1)
    worker = threading.Thread(
        target=processar_volumes,
        args=(fila_volumes, encerrar_worker, volume_cfg["update_interval"], volume_cfg["minimum_change"]),
        name="wpctl-worker",
    )
    worker.start()
    try:
        camera = cv2.VideoCapture(camera_cfg["device"], cv2.CAP_V4L2)
        if not camera.isOpened():
            raise RuntimeError(f"Não foi possível abrir /dev/video{camera_cfg['device']}.")
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg["width"])
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg["height"])
        camera.set(cv2.CAP_PROP_FPS, camera_cfg["fps"])
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        mp_maos = mp.solutions.hands
        mp_desenho = mp.solutions.drawing_utils
        volume_suave = 0.5
        ultimo_resultado = None
        numero_frame = 0

        with mp_maos.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=tracking_cfg["detection_confidence"],
            min_tracking_confidence=tracking_cfg["tracking_confidence"],
        ) as detector:
            while True:
                sucesso, imagem = camera.read()
                if not sucesso:
                    raise RuntimeError("Não foi possível ler a imagem da câmera.")
                imagem = cv2.flip(imagem, 1)
                if numero_frame % tracking_cfg["process_every_n_frames"] == 0:
                    ultimo_resultado = detector.process(cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB))
                numero_frame += 1
                resultado = ultimo_resultado
                altura, largura, _ = imagem.shape

                mao = selecionar_mao(resultado, tracking_cfg["control_hand"])
                aberta = mao is not None and palma_aberta(mao)
                alternou = ativacao.atualizar(aberta, time.monotonic())
                if alternou and activation_cfg["beep"]:
                    tocar_beep(ativacao.ativo)
                if mao is not None:
                    polegar, indicador = mao.landmark[4], mao.landmark[8]
                    px, py = int(polegar.x * largura), int(polegar.y * altura)
                    ix, iy = int(indicador.x * largura), int(indicador.y * altura)
                    gesto_ativacao = activation_cfg["enabled"] and aberta
                    if ativacao.ativo and not gesto_ativacao:
                        volume_alvo = converter_distancia_em_volume(
                            math.hypot(ix - px, iy - py),
                            volume_cfg["minimum_distance"],
                            volume_cfg["maximum_distance"],
                        )
                        volume_suave = suavizar_volume(
                            volume_suave, volume_alvo, volume_cfg["smoothing"]
                        )
                        enfileirar_volume(fila_volumes, volume_suave)

                    if interface_visivel:
                        mp_desenho.draw_landmarks(imagem, mao, mp_maos.HAND_CONNECTIONS)
                        porcentagem = round(volume_suave * 100)
                        cor = (0, 0, 255) if porcentagem < 15 else (0, 255, 0)
                        cv2.circle(imagem, (px, py), 10, cor, -1)
                        cv2.circle(imagem, (ix, iy), 10, cor, -1)
                        cv2.line(imagem, (px, py), (ix, iy), cor, 3)
                        topo = int(400 - volume_suave * 300)
                        cv2.rectangle(imagem, (30, 100), (65, 400), (255, 255, 255), 2)
                        cv2.rectangle(imagem, (30, topo), (65, 400), cor, -1)
                        cv2.putText(imagem, f"{porcentagem}%", (20, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor, 2)

                if interface_visivel:
                    texto_estado = "ATIVO" if ativacao.ativo else "INATIVO"
                    cor_estado = (0, 255, 0) if ativacao.ativo else (0, 0, 255)
                    cv2.putText(
                        imagem, texto_estado, (largura - 130, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, cor_estado, 2,
                    )
                    cv2.putText(
                        imagem, "Polegar + indicador: volume | Q/Esc: sair", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2,
                    )
                    cv2.imshow("GestureDeck", imagem)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                        break
    finally:
        encerrar_worker.set()
        try:
            if camera is not None:
                camera.release()
            if interface_visivel:
                cv2.destroyAllWindows()
        finally:
            worker.join()


def main() -> int:
    try:
        executar(carregar_configuracao())
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
    except (ErroConfiguracao, RuntimeError) as erro:
        print(f"Erro: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
