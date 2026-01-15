import json
import numpy as np


def parse(prefix, a, cost, p111, p222, p333, duration):
    x = [0, 0, 0]
    for i in range(len(p111)):
        x.append(int(p111[i]))
        x.append(int(p222[i]))
        x.append(int(p333[i]))

    x = np.array(x)
    y = x.reshape(-1, 3).sum(axis=1)

    fn = f"article/data/run_{prefix}_a_{a:02d}.json"
    with open(fn, "w") as f:
        json.dump(
            {
                "best_cost": cost,
                "max_actuations": a,
                "inp_file": "networks/any-town.inp",
                "verbose": 1,
                "duration": duration,
                "best_x": x.tolist(),
                "best_y": y.tolist(),
            },
            f,
            indent=4,
        )


#######################################
a = 3
prefix = "Costa2016"
cost = 3578.67
#       123456789012345678901234
p111 = "111111110011111111000110"
p222 = "010100000011111000000000"
p333 = "000000000000000010000100"
duration = 81.12 * 3600  # 292032
parse(prefix, a, cost, p111, p222, p333, duration)

prefix = "Cimorelli2020"
cost = 3575.54
#       123456789012345678901234
p111 = "111111110011101110000110"
p222 = "100100000011101110000000"
p333 = "000000000001100001000100"
duration = 11 * 60 + 3  # 663
parse(prefix, a, cost, p111, p222, p333, duration)

prefix = "Paola2025"
cost = 3577.40
#       123456789012345678901234
p111 = "111111110011111111000110"
p222 = "101000000011111000000000"
p333 = "000000000000000010000100"
duration = 960
parse(prefix, a, cost, p111, p222, p333, duration)

#######################################
a = 2
prefix = "Costa2016"
cost = 3618.59
#       123456789012345678901234
p111 = "111111111011111111000111"
p222 = "011000000011100000000000"
p333 = "000000000000001010000000"
duration = 36914
parse(prefix, a, cost, p111, p222, p333, duration)

prefix = "Cimorelli2020"
cost = 3580.11
#       123456789012345678901234
p111 = "101111110000000110000000"
p222 = "000000000011110000000110"
p333 = "111000000011111111000000"
duration = 11 * 60 + 3  # 663
parse(prefix, a, cost, p111, p222, p333, duration)

prefix = "Paola2025"
cost = 3606.22
#       123456789012345678901234
p111 = "111111110011111111000111"
p222 = "011000000011111000000000"
p333 = "000000000000000010000000"
duration = 904
parse(prefix, a, cost, p111, p222, p333, duration)

#######################################
a = 1

prefix = "Costa2016"
cost = 3916.98
#       123456789012345678901234
p111 = "111111111111111111100111"
p222 = "011000000000000000000000"
p333 = "000000000001110000000000"
duration = 425
parse(prefix, a, cost, p111, p222, p333, duration)

prefix = "Cimorelli2020"
cost = 3634.67
#       123456789012345678901234
p111 = "111111111111000110000000"
p222 = "100000000000000000000111"
p333 = "100000000011111111000000"
duration = 11 * 60 + 3  # 663
parse(prefix, a, cost, p111, p222, p333, duration)

prefix = "Paola2025"
cost = 3911.52
#       123456789012345678901234
p111 = "000100000000000000000000"
p222 = "111111111111111111100111"
p333 = "000000000001110000000000"
duration = 72
parse(prefix, a, cost, p111, p222, p333, duration)

prefix = "Souza2026"
# Load aggregated outputs
with open("article/data/outputs/agg_outputs.json", "r") as f:
    agg_data = json.load(f)

for a in range(1, 4):
    best_run = None
    min_cost = np.inf

    # Iterate through runs to find the best for current 'a'
    for run in agg_data.get("runs", []):
        config = run.get("config", {})
        if config.get("a") == a:
            best_payload = run.get("best")
            if best_payload:
                cost = best_payload.get("cost")
                if cost is not None and cost < min_cost:
                    min_cost = cost
                    best_run = run

    if best_run:
        best_payload = best_run.get("best", {})
        stats = best_run.get("stats", {})

        best_cost = best_payload.get("cost")
        best_x = best_payload.get("x")
        best_y = best_payload.get("y")
        duration = stats.get("duration")

        fn_json = f"article/data/run_{prefix}_a_{a:02d}.json"
        with open(fn_json, "w") as f:
            json.dump(
                {
                    "best_cost": best_cost,
                    "duration": duration,
                    "max_actuations": a,
                    "inp_file": "networks/any-town.inp",
                    "verbose": 1,
                    "best_x": best_x,
                    "best_y": best_y,
                },
                f,
                indent=4,
            )
    else:
        print(f"Warning: No runs found for a={a} in agg_outputs.json")
