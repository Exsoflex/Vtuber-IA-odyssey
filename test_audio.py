import sounddevice as sd

devices = sd.query_devices()
for i, d in enumerate(devices):
    if d['max_output_channels'] > 0:
        print(f'  [{i}] {d["name"]} (out: {d["max_output_channels"]} ch)')