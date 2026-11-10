"""Robust replacement for meter.py used by combined_sweep_robust.py.

IMPORTANT: Assumes the instrument responds to *TRG with a five-field CSV line,
as in the original implementation. Confirm against the instrument manual.
"""
import time
from datetime import datetime, timezone
import logging
import serial
import numpy as np

LOG = logging.getLogger(__name__)


class MeterCommunicationError(RuntimeError):
    pass


class Meter:
    def __init__(self, port, baudrate=115200, timeout=8.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.conn = None
        self.average = 1

    def connect(self):
        self.close()
        self.conn = serial.Serial(self.port, self.baudrate, timeout=self.timeout,
                                  write_timeout=3.0)
        time.sleep(0.2)
        LOG.info('Meter port opened: %s', self.port)

    def close(self):
        conn = self.conn
        self.conn = None
        if conn is not None and conn.is_open:
            conn.close()

    disconnect = close

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _send(self, command, delay=0.1):
        if self.conn is None or not self.conn.is_open:
            raise MeterCommunicationError('LCR serial connection is not open')
        try:
            payload = (command + '\n').encode('ascii')
            written = self.conn.write(payload)
            self.conn.flush()
            if written != len(payload):
                raise MeterCommunicationError(f'Incomplete write of {command!r}')
        except serial.SerialException as exc:
            raise MeterCommunicationError(f'LCR write failed for {command!r}') from exc
        if delay:
            time.sleep(delay)

    def set_meas_page(self):
        self._send('DISP:PAGE MEAS', 1.0)

    def set_function_impedance(self):
        self._send('FUNC Z-thd')

    def set_bias_voltage(self, v=0):
        self.bias = v
        self._send(f'BIAS {v}')

    def set_frequency(self, f=1000):
        self.frequency = f
        self._send(f'FREQ {f}')

    def set_stim_voltage(self, v=0.05):
        self.stim = v
        self._send(f'LEV:VOLT {v}')

    def set_average(self, samples):
        if samples < 1:
            raise ValueError('average must be >= 1')
        self.average = samples

    def set_slow_scan_speed(self):
        self._send('APER SLOW')

    def set_trigger(self):
        self._send('TRIG:SOUR BUS')
        self._send('TRIG:DLY min')

    def trigger_fetch(self):
        """Issue a single trigger and read exactly one response line.

        Do not retry automatically: repeating a trigger may duplicate a measurement.
        A timeout or malformed response is fatal to the current sweep.
        """
        self._send('*TRG', delay=0)
        try:
            raw = self.conn.readline()
        except serial.SerialException as exc:
            raise MeterCommunicationError('Serial read failed after *TRG') from exc
        if not raw:
            raise MeterCommunicationError(
                f'No response to *TRG within {self.conn.timeout} seconds '
                f'(frequency={getattr(self, "frequency", "unknown")})')
        if not raw.endswith(b'\n'):
            raise MeterCommunicationError(f'Unterminated LCR response: {raw!r}')
        return raw

    def decode_fetch(self, raw):
        try:
            fields = raw.decode('ascii').strip().split(',')
            if len(fields) != 5:
                raise ValueError(f'expected 5 CSV fields, received {len(fields)}')
            mag, phase = float(fields[0].strip()), float(fields[1].strip())
            if not np.isfinite(mag) or not np.isfinite(phase):
                raise ValueError('nonfinite magnitude or phase')
        except (UnicodeDecodeError, ValueError) as exc:
            raise MeterCommunicationError(f'Invalid LCR measurement: {raw!r}') from exc
        print(f'\t{mag}\t{phase}')
        return mag, phase

    def initialize_system(self, level, bias, average):
        self.set_meas_page()
        self.set_function_impedance()
        self.set_bias_voltage(bias)
        self.set_stim_voltage(level)
        self.set_average(average)
        self.set_slow_scan_speed()
        self.set_trigger()
        LOG.info('Initialized meter: bias=%s, level=%s, average=%s', bias, level, average)

    def _measure_once(self):
        # Wall-clock timestamps, in ISO 8601 format, for saver.py.
        # These bracket the trigger/read operation; they are not hardware timestamps.
        triggered_at = datetime.now(timezone.utc).isoformat()
        raw = self.trigger_fetch()
        arrived_at = datetime.now(timezone.utc).isoformat()
        result = self.decode_fetch(raw)
        return result, (triggered_at, arrived_at)

    def sweep_short_time_avg(self, frequencies, level, bias, average):
        self.initialize_system(level, bias, average)
        time.sleep(5)
        mags, phases, timings = [], [], []
        for frequency in frequencies:
            self.set_frequency(frequency)
            LOG.info('Frequency: %s Hz', frequency)
            for _ in range(2):
                self.trigger_fetch()
                time.sleep(0.5)
            mag_row, phase_row, time_row = [], [], []
            for _ in range(self.average):
                (mag, phase), timestamp_pair = self._measure_once()
                mag_row.append(mag)
                phase_row.append(phase)
                time_row.append(timestamp_pair)
                time.sleep(0.05)
            mags.append(mag_row)
            phases.append(phase_row)
            timings.append(time_row)
        return np.asarray(mags), np.asarray(phases), np.asarray(timings)

    def sweep_long_time_avg(self, frequencies, level, bias, average):
        self.initialize_system(level, bias, average)
        time.sleep(5)
        mags, phases, timings = [], [], []
        for _ in range(self.average):
            mag_row, phase_row, time_row = [], [], []
            for frequency in frequencies:
                self.set_frequency(frequency)
                LOG.info('Frequency: %s Hz', frequency)
                for _ in range(2):
                    self.trigger_fetch()
                    time.sleep(0.1)
                (mag, phase), timestamp_pair = self._measure_once()
                mag_row.append(mag)
                phase_row.append(phase)
                time_row.append(timestamp_pair)
                time.sleep(0.05)
            mags.append(mag_row)
            phases.append(phase_row)
            timings.append(time_row)
        return np.asarray(mags).T, np.asarray(phases).T, np.asarray(timings).T

    def sweep_short_time_avg_multi_bias(self, frequencies, level, bias, average):
        mags, phases, timings = [], [], []
        for value in bias:
            mag, phase, timing = self.sweep_short_time_avg(frequencies, level, value, average)
            mags.append(mag)
            phases.append(phase)
            timings.append(timing)
        return mags, phases, timings
