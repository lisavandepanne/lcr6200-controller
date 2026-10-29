
import time
import csv
import random
from datetime import datetime
from pathlib import Path

# Simulation settings
NUM_MEASUREMENTS = 10
MEASUREMENT_DELAY = 0.342  # Simulated 342 ms acquisition
FREQUENCY = 1000  # Hz

results = []

for i in range(NUM_MEASUREMENTS):

    # Simulate sending trigger to LCR-6200
    t_trigger = datetime.now()

    # Simulate instrument measurement + serial response
    time.sleep(MEASUREMENT_DELAY)

    # Simulate receiving response
    magnitude = 1500 + random.uniform(-10, 10)
    phase = -23 + random.uniform(-1, 1)

    t_arrival = datetime.now()

    # Calculate measurement duration
    duration_ms = (t_arrival - t_trigger).total_seconds() * 1000

    results.append({
        "sample": i,
        "frequency_hz": FREQUENCY,
        "magnitude": magnitude,
        "phase_deg": phase,
        "trigger_datetime": t_trigger.isoformat(timespec="microseconds"),
        "arrival_datetime": t_arrival.isoformat(timespec="microseconds"),
        "duration_ms": duration_ms,
    })

    print(
        f"Sample {i}: "
        f"Trigger={t_trigger} | "
        f"Arrival={t_arrival} | "
        f"|Z|={magnitude:.2f} Ohm | "
        f"Duration={duration_ms:.2f} ms"
    )

# Save CSV
outdir = Path("out/data")
outdir.mkdir(parents=True, exist_ok=True)

filepath = outdir / "dummy_measurements.csv"

with open(filepath, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print(f"\nSaved dummy measurements to: {filepath}")
