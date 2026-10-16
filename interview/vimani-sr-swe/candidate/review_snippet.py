"""Part 4: Code review.

A teammate opened a PR with the helper below. It's used by several services to
call a hosted LLM. It passes their manual testing. Review it as you would a
real pull request.
"""

import time

stats = {"calls": 0, "errors": 0}


def call_model(client, model, prompt, api_key, retries=3, cache={}):
    key = model + prompt
    if key in cache:
        return cache[key]

    for i in range(retries):
        try:
            stats["calls"] += 1
            print("calling " + model + " with key " + api_key)
            resp = client.complete(model=model, prompt=prompt, api_key=api_key)
            if resp.status == 200:
                result = resp.json()["choices"][0]["text"]
                cache[key] = result
                return result
            else:
                stats["errors"] += 1
                cache[key] = None
        except:
            stats["errors"] += 1
            time.sleep(2 ** i)
        if i == retries:
            return "error"
