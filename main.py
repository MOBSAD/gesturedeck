"""Ponto de entrada e loop de câmera do GestureDeck."""

from __future__ import annotations

import math
import time
from typing import Any

from actions import ExecutorAcoes, LimitadorVolume, WorkerAcoes
from config import CONFIGURACAO_PADRAO, ErroConfiguracao, carregar_configuracao
from gestures import (
    ControleAtivacao,
    MotorGestos,
    classificar_gesto,
    processar_estado_gesto,
    selecionar_mao,
)


def limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(valor, maximo))


def converter_distancia_em_volume(
    distancia: float, distancia_minima: float, distancia_maxima: float
) -> float:
    proporcao = (distancia - distancia_minima) / (distancia_maxima - distancia_minima)
    return limitar(proporcao, 0.0, 1.0)


def suavizar_volume(atual: float, alvo: float, fator: float) -> float:
    return limitar(atual + (alvo - atual) * limitar(fator, 0.0, 1.0), 0.0, 1.0)


def _desenhar_interface(
    cv2: Any,
    imagem: Any,
    ativo: bool,
    candidato: str | None,
    confirmado: str | None,
    acao: str | None,
    sucesso: bool | None,
    volume: float,
    progresso: float,
) -> None:
    altura, largura, _ = imagem.shape
    estado, cor_estado = ("ATIVO", (0, 255, 0)) if ativo else ("INATIVO", (0, 0, 255))
    cv2.putText(imagem, estado, (largura - 130, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, cor_estado, 2)
    linhas = (
        (f"Candidato: {candidato or '-'}", (0, 215, 255)),
        (f"Confirmado: {confirmado or '-'}", (255, 255, 0)),
        (f"Acao: {acao or '-'}", (0, 255, 0) if sucesso is not False else (0, 0, 255)),
        (f"Volume: {round(volume * 100)}%", (255, 255, 255)),
    )
    for indice, (texto, cor) in enumerate(linhas):
        cv2.putText(imagem, texto, (16, 28 + indice * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, cor, 2)
    largura_barra = 180
    fim = 16 + int(largura_barra * limitar(progresso, 0.0, 1.0))
    cv2.rectangle(imagem, (16, 132), (16 + largura_barra, 143), (100, 100, 100), 1)
    cv2.rectangle(imagem, (16, 132), (fim, 143), (0, 215, 255), -1)
    cv2.putText(
        imagem, "Q/Esc: sair", (16, altura - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
    )


def executar(configuracao: dict[str, dict[str, Any]]) -> None:
    import cv2
    import mediapipe as mp

    camera_cfg = configuracao["camera"]
    tracking_cfg = configuracao["tracking"]
    volume_cfg = configuracao["volume"]
    activation_cfg = configuracao["activation"]
    detection_cfg = configuracao["gesture_detection"]
    interface_visivel = configuracao["interface"]["visible"]

    ativacao = ControleAtivacao(
        activation_cfg["enabled"], activation_cfg["hold_seconds"],
        activation_cfg["cooldown"], activation_cfg["start_active"],
    )
    motor = MotorGestos(
        configuracao["gestures"], detection_cfg["stability_seconds"],
        detection_cfg["release_seconds"], detection_cfg["default_cooldown"],
        configuracao["gesture_cooldowns"],
    )
    limitador_volume = LimitadorVolume(volume_cfg["update_interval"], volume_cfg["minimum_change"])
    executor = ExecutorAcoes()
    executor.verificar_dependencias()
    worker = WorkerAcoes(executor, beep=activation_cfg["beep"])
    worker.iniciar()

    camera = None
    volume_suave = 0.5
    confirmado: str | None = None
    acao_exibida: str | None = None
    sucesso_acao: bool | None = None
    feedback_ate = 0.0
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
                agora = time.monotonic()
                mao = selecionar_mao(ultimo_resultado, tracking_cfg["control_hand"])
                gesto = classificar_gesto(mao) if mao is not None else None

                palma = gesto == "open_palm"
                alternou, estado = processar_estado_gesto(gesto, agora, ativacao, motor)
                if alternou:
                    confirmado = "open_palm"
                    acao_exibida = "activate" if ativacao.ativo else "deactivate"
                    sucesso_acao = True
                    feedback_ate = agora + 1.5
                    if activation_cfg["beep"]:
                        worker.adicionar("beep", acao_exibida)

                if estado.acao:
                    worker.adicionar(estado.acao)
                    confirmado = estado.confirmado
                    acao_exibida = estado.acao
                    sucesso_acao = None
                    feedback_ate = agora + 1.5

                if (
                    mao is not None
                    and gesto == "pinch"
                    and ativacao.ativo
                    and configuracao["gestures"]["pinch"] == "volume"
                ):
                    polegar, indicador = mao.landmark[4], mao.landmark[8]
                    altura, largura, _ = imagem.shape
                    distancia_pixels = math.hypot(
                        (indicador.x - polegar.x) * largura,
                        (indicador.y - polegar.y) * altura,
                    )
                    alvo = converter_distancia_em_volume(
                        distancia_pixels, volume_cfg["minimum_distance"], volume_cfg["maximum_distance"]
                    )
                    volume_suave = suavizar_volume(volume_suave, alvo, volume_cfg["smoothing"])
                    if limitador_volume.aceitar(volume_suave, agora):
                        worker.adicionar("volume", volume_suave)

                for resultado in worker.coletar_resultados():
                    acao_exibida = resultado.acao
                    sucesso_acao = resultado.sucesso
                    feedback_ate = agora + 1.5
                if agora >= feedback_ate:
                    confirmado = None
                    acao_exibida = None
                    sucesso_acao = None

                if interface_visivel:
                    if mao is not None:
                        mp_desenho.draw_landmarks(imagem, mao, mp_maos.HAND_CONNECTIONS)
                    progresso = estado.progresso
                    if palma and activation_cfg["enabled"]:
                        progresso = ativacao.progresso(agora)
                    candidato_exibido = estado.candidato
                    if palma:
                        candidato_exibido = "open_palm"
                    elif ativacao.ativo and gesto == "pinch":
                        candidato_exibido = "pinch"
                    _desenhar_interface(
                        cv2, imagem, ativacao.ativo, candidato_exibido, confirmado,
                        acao_exibida, sucesso_acao, volume_suave, progresso,
                    )
                    cv2.imshow("GestureDeck", imagem)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                        break
    finally:
        try:
            if camera is not None:
                camera.release()
            if interface_visivel:
                cv2.destroyAllWindows()
        finally:
            worker.encerrar()


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
