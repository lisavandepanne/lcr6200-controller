import matplotlib.pyplot as plt
import numpy as np
import datetime
from pathlib import Path


# Accepts vectors in the form of
# frequencies[]
# mag[frequencies, samples][?] and
# phase[frequencies, samples][?]
# bias_list[]
def make_figure(frequencies, mag, phase, bias_list, outdir=None):
    colors = [
        "tab:blue",
        "tab:orange",
        "tab:green",
        "tab:red",
        "tab:purple"
    ]

    mag_list = mag if len(bias_list) > 1 else [mag]
    phase_list = phase if len(bias_list) > 1 else [phase]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    for i, b_val in enumerate(bias_list):
        m = mag_list[i]
        p = phase_list[i]

        mag_mean = np.mean(m, axis=1)
        mag_std = np.std(m, axis=1)
        phase_mean = np.mean(np.unwrap(p), axis=1)
        phase_std = np.std(np.unwrap(p), axis=1)

        color = colors[i % len(colors)]

        # Adjust label and alpha based on whether it's single or multi-bias
        if len(bias_list) == 1:
            mag_label, phase_label = "Mean Magnitude", "Mean Phase"
            fill_alpha = 0.2
        else:
            mag_label = phase_label = f"Bias: {b_val}V"
            fill_alpha = 0.1

        # Magnitude plot
        ax1.plot(frequencies, mag_mean, color=color, label=mag_label, linewidth=2)
        ax1.fill_between(
            frequencies,
            mag_mean - mag_std,
            mag_mean + mag_std,
            color=color,
            alpha=fill_alpha,
            label="± 1 Std Dev" if len(bias_list) == 1 else None,
        )

        # Phase plot
        ax2.plot(frequencies, phase_mean, color=color, label=phase_label, linewidth=2)
        ax2.fill_between(
            frequencies,
            phase_mean - phase_std,
            phase_mean + phase_std,
            color=color,
            alpha=fill_alpha,
            label="± 1 Std Dev" if len(bias_list) == 1 else None,
        )

    title_suffix = "" if len(bias_list) == 1 else " (Multi-Bias)"

    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlabel("Frequency (Hz)", fontsize=11)
    ax1.set_ylabel("Magnitude", fontsize=11)
    ax1.set_title(f"Frequency Sweep: Magnitude{title_suffix}", fontsize=12)
    ax1.grid(True, which="both", ls="--", alpha=0.6)
    ax1.legend()

    ax2.set_xscale("log")
    ax2.set_ylim(-110, 10)
    ax2.set_xlabel("Frequency (Hz)", fontsize=11)
    ax2.set_ylabel("Phase (Degrees)", fontsize=11)
    ax2.set_title(f"Frequency Sweep: Phase{title_suffix}", fontsize=12)
    ax2.grid(True, which="both", ls="--", alpha=0.6)
    ax2.legend()

    plt.tight_layout()
    
    if outdir is not None:
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        plt.savefig(outdir / datetime.datetime.today().strftime("%y%m%d-%H%M.pdf"))

    plt.show()

