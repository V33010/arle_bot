import time

total = 1000

for i in range(1, total + 1):
    print(f"[{i}/{total}]", end="\r", flush=True)
    time.sleep(0.01)  # Just to simulate some processing
