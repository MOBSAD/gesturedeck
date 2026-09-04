"""Controle de volume por gestos usando uma webcam."""

from __future__ import annotations

import math
import queue
import subprocess
import threading
import time

CAMERA_DEVICE = "/dev/video0"
DISTANCIA_MINIMA = 25.0
DISTANCIA_MAXIMA = 180.0
SUAVIZACAO = 0.18
INTERVALO_COMANDO = 0.15
MUDANCA_MINIMA = 0.03


def limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(valor, maximo))


def converter_distancia_em_volume(distancia: float) -> float:
    proporcao = (distancia - DISTANCIA_MINIMA) / (DISTANCIA_MAXIMA - DISTANCIA_MINIMA)
    return limitar(proporcao, 0.0, 1.0)


def suavizar_volume(atual: float, alvo: float, fator: float = SUAVIZACAO) -> float:
    fator = limitar(fator, 0.0, 1.0)
    return limitar(atual + (alvo - atual) * fator, 0.0, 1.0)


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
    """Substitui qualquer volume pendente pelo valor mais recente."""
    while True:
        try:
            fila.put_nowait(volume)
            return
        except queue.Full:
            try:
                fila.get_nowait()
            except queue.Empty:
                pass


def _obter_volume_mais_recente(
    fila: queue.Queue[float], primeiro: float
) -> float:
    volume = primeiro
    while True:
        try:
            volume = fila.get_nowait()
        except queue.Empty:
            return volume


def processar_volumes(
    fila: queue.Queue[float], encerrar: threading.Event
) -> None:
    """Envia volumes ao wpctl sem bloquear a captura e a interface."""
    ultimo_volume = -1.0
    ultimo_comando = 0.0

    while not encerrar.is_set():
        try:
            volume = fila.get(timeout=0.05)
        except queue.Empty:
            continue

        volume = _obter_volume_mais_recente(fila, volume)
        espera = INTERVALO_COMANDO - (time.monotonic() - ultimo_comando)
        if espera > 0 and encerrar.wait(espera):
            break

        volume = _obter_volume_mais_recente(fila, volume)
        if abs(volume - ultimo_volume) < MUDANCA_MINIMA:
            continue

        ultimo_comando = time.monotonic()
        try:
            definir_volume(volume)
        except RuntimeError as erro:
            print(f"Erro: {erro}")
        else:
            ultimo_volume = volume


def executar() -> None:
    import cv2
    import mediapipe as mp

    camera = None
    encerrar_worker = threading.Event()
    fila_volumes: queue.Queue[float] = queue.Queue(maxsize=1)
    worker = threading.Thread(
        target=processar_volumes,
        args=(fila_volumes, encerrar_worker),
        name="wpctl-worker",
    )
    worker.start()
    try:
        camera = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
        if not camera.isOpened():
            raise RuntimeError(f"Não foi possível abrir {CAMERA_DEVICE}.")

        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        camera.set(cv2.CAP_PROP_FPS, 30)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        mp_maos = mp.solutions.hands
        mp_desenho = mp.solutions.drawing_utils
        volume_suave = 0.5
        ultimo_resultado = None
        numero_frame = 0

        with mp_maos.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.65,
            min_tracking_confidence=0.65,
        ) as detector:
            while True:
                sucesso, imagem = camera.read()
                if not sucesso:
                    raise RuntimeError("Não foi possível ler a imagem da câmera.")

                imagem = cv2.flip(imagem, 1)
                if numero_frame % 2 == 0:
                    ultimo_resultado = detector.process(
                        cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)
                    )
                numero_frame += 1
                resultado = ultimo_resultado
                altura, largura, _ = imagem.shape

                if resultado and resultado.multi_hand_landmarks:
                    mao = resultado.multi_hand_landmarks[0]
                    mp_desenho.draw_landmarks(imagem, mao, mp_maos.HAND_CONNECTIONS)
                    polegar, indicador = mao.landmark[4], mao.landmark[8]
                    px, py = int(polegar.x * largura), int(polegar.y * altura)
                    ix, iy = int(indicador.x * largura), int(indicador.y * altura)

                    volume_alvo = converter_distancia_em_volume(math.hypot(ix - px, iy - py))
                    volume_suave = suavizar_volume(volume_suave, volume_alvo)
                    porcentagem = round(volume_suave * 100)
                    cor = (0, 0, 255) if porcentagem < 15 else (0, 255, 0)

                    cv2.circle(imagem, (px, py), 10, cor, -1)
                    cv2.circle(imagem, (ix, iy), 10, cor, -1)
                    cv2.line(imagem, (px, py), (ix, iy), cor, 3)
                    topo = int(400 - volume_suave * 300)
                    cv2.rectangle(imagem, (30, 100), (65, 400), (255, 255, 255), 2)
                    cv2.rectangle(imagem, (30, topo), (65, 400), cor, -1)
                    cv2.putText(imagem, f"{porcentagem}%", (20, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor, 2)

                    enfileirar_volume(fila_volumes, volume_suave)

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
            cv2.destroyAllWindows()
        finally:
            worker.join()


def main() -> int:
    try:
        executar()
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
    except RuntimeError as erro:
        print(f"Erro: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
