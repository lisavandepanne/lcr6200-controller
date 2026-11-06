
import serial
import numpy as np
import time
from datetime import datetime

SLOW_SCAN_SPEED_FREQUENCY = [10, 20, 100, 1000, 2000, 10000, 100000, 300000]  # Hz
SLOW_SCAN_SPEED_TIME = [1600, 800, 483, 342, 336, 332, 332, 332]  # ms


class Meter:
    conn: serial.Serial

    def __init__(self, port, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.conn = None

    def connect(self):
        self.conn = serial.Serial(
            self.port,
            self.baudrate,
            timeout=1.5 * max(SLOW_SCAN_SPEED_TIME) / 1000
        )
        time.sleep(0.1)

    def set_meas_page(self):
        self.conn.write(b"DISP:PAGE MEAS\n")
        time.sleep(1)

    def set_function_impedance(self):
        self.conn.write(b"FUNC Z-thd\n")
        time.sleep(0.1)

    def set_bias_voltage(self, v=0):
        self.bias = v
        self.conn.write(f"BIAS {v}\n".encode())
        time.sleep(0.1)

    def set_frequency(self, f=1000):
        self.frequency = f
        self.conn.write(f"FREQ {f}\n".encode())
        time.sleep(0.1)

    def set_stim_voltage(self, v=0.05):
        self.stim = v
        self.conn.write(f"LEV:VOLT {v}\n".encode())
        time.sleep(0.1)

    def set_average(self, samples):
        self.average = samples

    def set_slow_scan_speed(self):
        self.conn.write(b"APER SLOW\n")
        time.sleep(0.1)

    def set_trigger(self):
        self.conn.write(b"TRIG:SOUR BUS\n")
        time.sleep(0.1)
        self.conn.write(b"TRIG:DLY min\n")
        time.sleep(0.1)

    def trigger_fetch(self):
        # Record trigger datetime
        t_trigger = datetime.now().isoformat(timespec="microseconds")

        # Trigger measurement
        self.conn.write(b"*TRG\n")

        # Wait for measurement response
        raw = self.conn.readline()

        # Record arrival datetime
        t_arrival = datetime.now().isoformat(timespec="microseconds")

        if not raw:
            raise TimeoutError("No response from LCR-6200")

        return raw, t_trigger, t_arrival

    def decode_fetch(self, data: bytes):
        mag, phase, _, _, _ = data.decode("utf-8").split(",")
        print(f"\t{mag}\t{phase}")
        return float(mag.strip()), float(phase.strip())

    def initialize_system(self, level, bias, average):
        self.set_meas_page()
        self.set_function_impedance()
        self.set_bias_voltage(bias)
        self.set_stim_voltage(level)
        self.set_average(average)
        self.set_slow_scan_speed()
        self.set_trigger()

        print(
            f"Initialized System Vdc={bias}; "
            f"Vac={level}; Avg={average}."
        )

    def sweep_short_time_avg(self, frequencies, level, bias, average):
        self.initialize_system(level, bias, average)

        time.sleep(5)  # Wait before starting measurements

        results_magnitude = []
        results_phase = []
        results_timing = []

        for i, frequency in enumerate(frequencies):
            results_magnitude.append([])
            results_phase.append([])
            results_timing.append([])

            self.set_frequency(frequency)
            print(f"Set frequency to {frequency}.")
        #debug
        self.set_frequency(frequency)
        print(f"Set frequency to {frequency}.")

        for j in range(2):
            print(f"Reset trigger {j + 1}: sending")
            raw = self.trigger_fetch()
            print(f"Reset trigger {j + 1}: received {raw!r}")
            time.sleep(0.5)

        for j in range(self.average):
            print(f"Measurement trigger {j + 1}: sending")
            raw = self.trigger_fetch()
            print(f"Measurement trigger {j + 1}: received {raw!r}")

            data = self.decode_fetch(raw)
            results_magnitude[i].append(data[0])
            results_phase[i].append(data[1])
            time.sleep(0.05)
        #debug    
            # Trigger twice to reset the value
            # for _ in range(2):
            #     self.trigger_fetch()
            #     time.sleep(0.5)

            # Perform measurements and record timestamps
            for _ in range(self.average):
                raw, t_trigger, t_arrival = self.trigger_fetch()
                mag, phase = self.decode_fetch(raw)

                results_magnitude[i].append(mag)
                results_phase[i].append(phase)
                results_timing[i].append([t_trigger, t_arrival])

                # Calculate duration in milliseconds
                duration_ms = (
                    datetime.fromisoformat(t_arrival)
                    - datetime.fromisoformat(t_trigger)
                ).total_seconds() * 1000

                print(
                    f"Trigger: {t_trigger} | "
                    f"Arrival: {t_arrival} | "
                    f"Duration: {duration_ms:.3f} ms"
                )

                time.sleep(0.05)

        return (
            np.array(results_magnitude),
            np.array(results_phase),
            np.array(results_timing),
        )

    def sweep_long_time_avg(self, frequencies, level, bias, average):
        self.initialize_system(level, bias, average)

        time.sleep(5)  # Wait before starting measurements

        results_magnitude = []
        results_phase = []
        results_timing = []

        for i in range(self.average):
            results_magnitude.append([])
            results_phase.append([])
            results_timing.append([])

            for frequency in frequencies:
                self.set_frequency(frequency)
                print(f"Set frequency to {frequency}.")

                # Trigger twice to reset the value
                for _ in range(2):
                    self.trigger_fetch()
                    time.sleep(0.1)

                # Measure and record timestamps
                raw, t_trigger, t_arrival = self.trigger_fetch()
                mag, phase = self.decode_fetch(raw)

                results_magnitude[i].append(mag)
                results_phase[i].append(phase)
                results_timing[i].append([t_trigger, t_arrival])

                # Calculate duration in milliseconds
                duration_ms = (
                    datetime.fromisoformat(t_arrival)
                    - datetime.fromisoformat(t_trigger)
                ).total_seconds() * 1000

                print(
                    f"Trigger: {t_trigger} | "
                    f"Arrival: {t_arrival} | "
                    f"Duration: {duration_ms:.3f} ms"
                )

                time.sleep(0.05)

        # Transpose arrays so dimensions are:
        # (frequencies, samples)
        magnitude = np.array(results_magnitude).T
        phase = np.array(results_phase).T

        # Timing dimensions:
        # (frequencies, samples, 2)
        timing = np.transpose(
            np.array(results_timing),
            (1, 0, 2)
        )

        return magnitude, phase, timing

    def sweep_short_time_avg_multi_bias(
        self, frequencies, level, bias, average
    ):
        res_mag = []
        res_phase = []
        res_timing = []

        for b in bias:
            mag, phase, timing = self.sweep_short_time_avg(
                frequencies, level, b, average
            )

            res_mag.append(mag)
            res_phase.append(phase)
            res_timing.append(timing)

        return res_mag, res_phase, res_timing

    def close(self):
        if self.conn is not None and self.conn.is_open:
            self.conn.close()

    def __del__(self):
        self.close()
