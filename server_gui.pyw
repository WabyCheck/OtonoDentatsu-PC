#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import socket
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

import numpy as np
import sounddevice as sd
import opuslib
from PIL import Image, ImageDraw
import pystray


SETTINGS_FILE = 'settings.json'


class AudioSender:
    def __init__(self):
        self.stream = None
        self.sock = None
        self.encoder = None
        self.running = False
        self.target = ("127.0.0.1", 5000)
        self.sample_rate = 48000
        self.frame_size = 240
        self.bitrate = 128000
        self.device_id = None

        # state protected by GIL; callback is same process/thread context from PortAudio

    def configure(self, target_ip: str, target_port: int, sample_rate: int, frame_size: int, bitrate: int, device_id: int):
        self.target = (target_ip, int(target_port))
        self.sample_rate = int(sample_rate)
        self.frame_size = int(frame_size)
        self.bitrate = int(bitrate)
        self.device_id = device_id

    def _ensure_encoder(self):
        enc = opuslib.Encoder(self.sample_rate, 2, opuslib.APPLICATION_AUDIO)
        enc.bitrate = self.bitrate
        enc.complexity = 10
        enc.signal_type = opuslib.SIGNAL_MUSIC
        self.encoder = enc

    def _open_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _callback(self, indata, frames, time, status):
        if not self.running or self.encoder is None or self.sock is None:
            return
        if status:
            # PortAudio status warnings can be ignored or logged
            pass
        try:
            # Ensure stereo int16 PCM expected by opuslib
            if indata.dtype != np.int16:
                audio_int16 = (indata * 32767.0).astype(np.int16, copy=False)
            else:
                audio_int16 = indata

            # stereo: channels 0/1
            if audio_int16.shape[1] >= 2:
                stereo = audio_int16[:, :2]
            else:
                # duplicate mono to stereo
                stereo = np.repeat(audio_int16, 2, axis=1)

            # opus expects bytes for frame_size samples per channel
            pcm_bytes = stereo.tobytes(order='C')
            packet = self.encoder.encode(pcm_bytes, self.frame_size)
            self.sock.sendto(packet, self.target)
        except Exception:
            # swallow to keep callback realtime-safe
            pass

    def start(self):
        if self.running:
            return
        self._ensure_encoder()
        self._open_socket()

        # Open input stream with 2 channels; PortAudio will map first two device channels
        self.stream = sd.InputStream(
            device=self.device_id,
            samplerate=self.sample_rate,
            channels=2,
            blocksize=self.frame_size,
            dtype='int16',
            callback=self._callback,
        )
        self.stream.start()
        self.running = True

    def stop(self):
        if not self.running:
            return
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        finally:
            self.stream = None
        try:
            if self.sock is not None:
                self.sock.close()
        finally:
            self.sock = None
        self.encoder = None
        self.running = False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OND Client")
        self.resizable(False, False)

        self.sender = AudioSender()

        # UI variables
        self.var_device = tk.StringVar()
        self.var_port = tk.StringVar(value="5000")
        self.var_samplerate = tk.StringVar(value="48000")
        self.var_bitrate = tk.StringVar(value="128000")
        self.var_framesize = tk.StringVar(value="240")
        self.status_var = tk.StringVar(value="Остановлено")
        self.local_ip_var = tk.StringVar(value=self._detect_local_ip())

        self.devices = []  # list[(id, name)]

        self._build_ui()
        self._load_settings()
        self._populate_devices()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # tray icon
        try:
            self._init_tray()
        except Exception:
            pass

    def _build_ui(self):
        pad = {'padx': 8, 'pady': 4}

        frm = ttk.Frame(self)
        frm.grid(row=0, column=0, sticky='nsew', padx=10, pady=10)

        ttk.Label(frm, text="Устройство ввода").grid(row=0, column=0, sticky='w', **pad)
        self.cmb_device = ttk.Combobox(frm, textvariable=self.var_device, width=40, state='readonly')
        self.cmb_device.grid(row=0, column=1, columnspan=2, sticky='ew', **pad)
        ttk.Button(frm, text="Обновить", command=self._populate_devices).grid(row=0, column=3, **pad)

        ttk.Label(frm, text="IP ПК").grid(row=1, column=0, sticky='w', **pad)
        ttk.Label(frm, textvariable=self.local_ip_var).grid(row=1, column=1, sticky='w', **pad)

        ttk.Label(frm, text="Порт (HELLO)").grid(row=2, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_port, width=10).grid(row=2, column=1, sticky='w', **pad)
        ttk.Label(frm, text="Статус подключения: ожидание HELLO от телефона").grid(row=2, column=2, columnspan=2, sticky='w', **pad)

        ttk.Label(frm, text="Sample rate").grid(row=3, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_samplerate, width=10).grid(row=3, column=1, sticky='w', **pad)

        ttk.Label(frm, text="Bitrate (bps)").grid(row=3, column=2, sticky='e', **pad)
        ttk.Entry(frm, textvariable=self.var_bitrate, width=10).grid(row=3, column=3, sticky='w', **pad)

        ttk.Label(frm, text="Frame size").grid(row=4, column=0, sticky='w', **pad)
        ttk.Entry(frm, textvariable=self.var_framesize, width=10).grid(row=4, column=1, sticky='w', **pad)

        self.btn_toggle = ttk.Button(frm, text="Старт", command=self.on_toggle)
        self.btn_toggle.grid(row=5, column=0, columnspan=4, sticky='ew', **pad)

        ttk.Label(frm, textvariable=self.status_var, foreground='green').grid(row=6, column=0, columnspan=4, sticky='w', **pad)

    def _populate_devices(self):
        try:
            devs = sd.query_devices()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось получить устройства: {e}")
            return

        self.devices.clear()
        items = []
        for idx, d in enumerate(devs):
            if d.get('max_input_channels', 0) > 0:
                name = f"{idx}: {d.get('name', 'Unknown')}"
                self.devices.append((idx, d.get('name', 'Unknown')))
                items.append(name)
        self.cmb_device['values'] = items

        # select previous or first
        if self.var_device.get() and any(self.var_device.get().startswith(f"{i}:") for i, _ in self.devices):
            self.cmb_device.set(self.var_device.get())
        elif items:
            self.cmb_device.current(0)

    def _save_settings(self):
        data = {
            'device': self.var_device.get(),
            'port': self.var_port.get(),
            'samplerate': self.var_samplerate.get(),
            'bitrate': self.var_bitrate.get(),
            'framesize': self.var_framesize.get(),
        }
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.var_device.set(data.get('device', ''))
            self.var_port.set(data.get('port', self.var_port.get()))
            self.var_samplerate.set(data.get('samplerate', self.var_samplerate.get()))
            self.var_bitrate.set(data.get('bitrate', self.var_bitrate.get()))
            self.var_framesize.set(data.get('framesize', self.var_framesize.get()))
        except Exception:
            pass

    def on_start(self):
        try:
            if not self.cmb_device.get():
                messagebox.showwarning("Внимание", "Выберите устройство ввода")
                return

            dev_id = int(self.cmb_device.get().split(':', 1)[0])
            port = int(self.var_port.get())
            sr = int(self.var_samplerate.get())
            fs = int(self.var_framesize.get())
            br = int(self.var_bitrate.get())

            # target устанавливается после получения HELLO; временно None
            self.sender.configure("0.0.0.0", 0, sr, fs, br, dev_id)
            self.sender.start()
            self.btn_toggle.configure(text='Стоп', state='normal')
            self.status_var.set(f"Запущено → ожидание HELLO на порту {port} @ {sr}Hz, {br}bps, frame={fs}")
            self._start_hello_listener(port)
            self._save_settings()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось запустить: {e}")

    def on_stop(self):
        try:
            self.sender.stop()
        finally:
            self.btn_toggle.configure(text='Старт', state='normal')
            self.status_var.set("Остановлено")
            self._stop_hello_listener()

    def on_toggle(self):
        self.btn_toggle.configure(state='disabled')
        if self.sender.running:
            self.on_stop()
        else:
            self.on_start()
        # state updated by on_start/on_stop

    def on_close(self):
        try:
            self.sender.stop()
        finally:
            self.destroy()
            self._stop_hello_listener()
            try:
                if hasattr(self, '_tray') and self._tray:
                    self._tray.stop()
            except Exception:
                pass

    def _detect_local_ip(self) -> str:
        # Try default route IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass
        # Fallback to hostname method
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith("127."):
                    return ip
        except Exception:
            pass
        return "0.0.0.0"

    def _start_hello_listener(self, port: int):
        self._hello_stop = threading.Event()
        self._hello_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._hello_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._hello_sock.bind(("0.0.0.0", int(port)))

        def run():
            while not self._hello_stop.is_set():
                try:
                    self._hello_sock.settimeout(0.5)
                    data, addr = self._hello_sock.recvfrom(1024)
                    if data and data.startswith(b"HELLO"):
                        # зафиксируем клиента
                        self.sender.target = (addr[0], addr[1])
                        self.status_var.set(f"Клиент: {addr[0]}:{addr[1]}")
                except socket.timeout:
                    continue
                except Exception:
                    break
        self._hello_thr = threading.Thread(target=run, daemon=True)
        self._hello_thr.start()

    def _stop_hello_listener(self):
        try:
            if hasattr(self, '_hello_stop') and self._hello_stop:
                self._hello_stop.set()
            if hasattr(self, '_hello_sock') and self._hello_sock:
                try:
                    self._hello_sock.close()
                except Exception:
                    pass
            if hasattr(self, '_hello_thr') and self._hello_thr and self._hello_thr.is_alive():
                self._hello_thr.join(timeout=1)
        except Exception:
            pass


if __name__ == '__main__':
    App().mainloop()

    
    
def _make_icon_image():
    img = Image.new('RGBA', (128, 128), (32, 96, 224, 255))
    d = ImageDraw.Draw(img)
    # simple white rectangle letters "OND"
    d.rectangle([16, 52, 48, 76], fill=(255, 255, 255, 255))
    d.rectangle([54, 52, 62, 76], fill=(255, 255, 255, 255))
    d.rectangle([62, 52, 86, 60], fill=(255, 255, 255, 255))
    d.rectangle([62, 68, 86, 76], fill=(255, 255, 255, 255))
    d.rectangle([90, 52, 112, 76], fill=(255, 255, 255, 255))
    return img


def _tray_menu(app: 'App'):
    return pystray.Menu(
        pystray.MenuItem('Открыть', lambda: app.deiconify()),
        pystray.MenuItem('Старт' if not app.sender.running else 'Стоп', lambda: app.on_toggle()),
        pystray.MenuItem('Выход', lambda: app.on_close())
    )


def _init_tray_for(app: 'App'):
    image = _make_icon_image()
    icon = pystray.Icon('OND Client', image, 'OND Client', _tray_menu(app))
    app._tray = icon
    def run():
        try:
            icon.run()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


# attach method to App dynamically to avoid refactor large class
def _init_tray(self: 'App'):
    _init_tray_for(self)

App._init_tray = _init_tray
