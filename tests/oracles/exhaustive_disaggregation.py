#!/usr/bin/env python3

import itertools
import json
import subprocess
import sys


SCENARIOS = (
    (3, 6, (0, 1, 2)),
    (9, 2, (0, 1)),
)


def aggregate(schedule):
    return tuple(sum(period) for period in schedule)


def required_cycles(schedule, pump_count, period_count):
    cycle_counts = []
    for pump in range(pump_count):
        switches = sum(
            schedule[period - 1][pump] != schedule[period][pump]
            for period in range(period_count)
        )
        if switches % 2 != 0:
            raise AssertionError("a periodic binary schedule must have an even switch count")
        cycle_counts.append(switches // 2)
    return max(cycle_counts)


def exhaustive_minimum_cycles(pump_count, period_count):
    minimum_cycles = {}
    for flattened in itertools.product((0, 1), repeat=pump_count * period_count):
        schedule = tuple(
            flattened[period * pump_count : (period + 1) * pump_count]
            for period in range(period_count)
        )
        aggregate_schedule = aggregate(schedule)
        cycles = required_cycles(schedule, pump_count, period_count)
        previous = minimum_cycles.get(aggregate_schedule)
        if previous is None or cycles < previous:
            minimum_cycles[aggregate_schedule] = cycles
    return minimum_cycles


def validate_witness(
    witness, aggregate_schedule, max_cycles, pump_count, period_count
):
    if len(witness) != period_count:
        raise AssertionError("witness has the wrong number of periods")
    if any(len(period) != pump_count for period in witness):
        raise AssertionError("witness has the wrong number of pumps")
    if any(status not in (0, 1) for period in witness for status in period):
        raise AssertionError("witness contains a non-binary status")
    if aggregate(tuple(tuple(period) for period in witness)) != aggregate_schedule:
        raise AssertionError("witness does not reproduce its aggregate schedule")
    if (
        required_cycles(
            tuple(tuple(period) for period in witness),
            pump_count,
            period_count,
        )
        > max_cycles
    ):
        raise AssertionError("witness exceeds the periodic cycle limit")


def query_cpp(query_executable, aggregate_schedules, pump_count, max_cycles):
    input_lines = "".join(json.dumps(schedule) + "\n" for schedule in aggregate_schedules)
    completed = subprocess.run(
        [query_executable, str(pump_count), str(max_cycles)],
        input=input_lines,
        text=True,
        capture_output=True,
        check=True,
    )
    output_lines = completed.stdout.splitlines()
    if len(output_lines) != len(aggregate_schedules):
        raise AssertionError("C++ query returned an unexpected number of responses")
    return [json.loads(line) for line in output_lines]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: exhaustive_disaggregation.py QUERY_EXECUTABLE")

    for pump_count, period_count, cycle_limits in SCENARIOS:
        minimum_cycles = exhaustive_minimum_cycles(pump_count, period_count)
        aggregate_schedules = list(
            itertools.product(range(pump_count + 1), repeat=period_count)
        )

        for max_cycles in cycle_limits:
            responses = query_cpp(
                sys.argv[1], aggregate_schedules, pump_count, max_cycles
            )
            for aggregate_schedule, response in zip(aggregate_schedules, responses):
                expected_feasible = minimum_cycles[aggregate_schedule] <= max_cycles
                if response["feasible"] != expected_feasible:
                    raise AssertionError(
                        f"pumps={pump_count}, periods={period_count}, "
                        f"schedule={aggregate_schedule}, max_cycles={max_cycles}: "
                        f"expected feasible={expected_feasible}, "
                        f"got {response['feasible']}"
                    )
                if expected_feasible:
                    validate_witness(
                        response["witness"],
                        aggregate_schedule,
                        max_cycles,
                        pump_count,
                        period_count,
                    )
                elif response["witness"] is not None:
                    raise AssertionError("an infeasible schedule returned a witness")


if __name__ == "__main__":
    main()
