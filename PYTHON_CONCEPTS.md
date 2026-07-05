# Python concepts used in this project (for a C# developer)

A jump-map: each concept has a **one-line explanation**, a **C# analogy**, a **tiny
example**, and a **link to a real line in this codebase** where it's used. Click a
link to open that exact line, or set a breakpoint there and watch it run.

> New to Python? Learn these top-to-bottom. The only truly *new* ideas coming from
> C# are **indentation-as-blocks**, **`with` (context managers)**, and **mutable
> objects passed by reference**. Everything else is a syntax swap.

---

## 0. Mental model: Python vs C#

| C# | Python |
|---|---|
| `{ }` blocks | **indentation** (4 spaces) |
| `using System;` | `import os` / `from x import y` |
| `null` | `None` |
| `var`, static types | dynamic types, optional type *hints* |
| `List<T>`, `Dictionary<K,V>` | `list`, `dict` |
| `foreach (var x in xs)` | `for x in xs:` |
| `$"{x}"` | `f"{x}"` |
| `record` | `@dataclass` |
| `using (var f = ...)` | `with ... as f:` |
| `Func<>` / `x => y` | `lambda x: y` |
| NuGet | `pip` + a `.venv` folder |
| `this` | `self` (written explicitly) |

---

## 1. Syntax essentials

- **Imports** — `import json` (whole module) vs `from dataclasses import dataclass`
  (specific names). A leading dot = *this package*: `from .config import settings`.
  → [agent.py:18](src/fintech_agent/agent.py:18), [agent.py:29](src/fintech_agent/agent.py:29)

- **Type hints** — `message: str`, `-> AgentResult`. Documentation + tooling; not
  enforced at runtime.
  → [agent.py:129](src/fintech_agent/agent.py:129)

- **f-strings** — `f"cost {x:.5f}"`. `{ }` interpolates; `:.5f` = 5 decimals,
  `:<26` = left-pad to 26, `:,.2f` = thousands + 2 decimals.
  → [agent.py:61](src/fintech_agent/agent.py:61), [tracing.py:69](src/fintech_agent/tracing.py:69), [tools.py:58](src/fintech_agent/tools.py:58)

- **`None`** — Python's `null`. Test with `is None`, not `== None`.
  → [agent.py:75](src/fintech_agent/agent.py:75)

- **Truthiness & `or`** — empty `""`/`[]`/`{}`/`0`/`None` are "falsy". `a or b`
  returns `a` if truthy else `b` (the "default value" trick).
  → [agent.py:77](src/fintech_agent/agent.py:77) (`approve_sensitive or (lambda ...)`),
  [agent.py:105](src/fintech_agent/agent.py:105) (`... or ""`)

- **`if / elif / else`** and the **ternary** `X if cond else Y`.
  → [agent.py:86](src/fintech_agent/agent.py:86), [agent.py:102](src/fintech_agent/agent.py:102)

- **`in`** — membership test. `name in SENSITIVE_TOOLS`.
  → [agent.py](src/fintech_agent/agent.py) (`_invoke`, the `sensitive = name in ...` line)

---

## 2. Functions & classes

- **`def` + `self`** — methods take `self` (the object) as the first parameter,
  like an explicit `this`.
  → [agent.py:129](src/fintech_agent/agent.py:129)

- **Keyword-only args (`*,`)** — everything after a lone `*` must be passed by
  name: `FintechAgent(enable_semantic_guardrail=True)`.
  → [agent.py:75](src/fintech_agent/agent.py:75)

- **`__init__`** — the constructor (runs on `FintechAgent(...)`).
  → [agent.py:75](src/fintech_agent/agent.py:75)

- **Dunder methods** — `__str__` runs on `print(obj)` / `str(obj)` (like C#
  `ToString()`).
  → [agent.py:56](src/fintech_agent/agent.py:56)

- **`@property`** — a method you access like a field (`rec.total_tokens`, no
  parentheses). Same as a C# get-only property.
  → [cost.py:31](src/fintech_agent/safety/cost.py:31), [cost.py:86](src/fintech_agent/safety/cost.py:86)

---

## 3. Dataclasses & decorators

- **`@dataclass`** — auto-generates the constructor from the fields (like a C#
  `record`). `@` = a **decorator** (wraps the thing below).
  → [agent.py:37](src/fintech_agent/agent.py:37), [cost.py:23](src/fintech_agent/safety/cost.py:23)

- **`field(default_factory=list)`** — gives each instance a **fresh** default
  (writing `= []` would secretly share one list — a classic Python bug).
  → [agent.py:49](src/fintech_agent/agent.py:49)

- **`@dataclass(frozen=True)`** — immutable (read-only) dataclass.
  → [config.py:41](src/fintech_agent/config.py:41)

- **Function decorators** — `@traceable(...)` wraps `run()` to record it as a
  trace node; `@lru_cache` caches a function's result; `@contextmanager` turns a
  generator into a `with`-block.
  → [agent.py:128](src/fintech_agent/agent.py:128), [knowledge.py:23](src/fintech_agent/knowledge.py:23), [tracing.py:39](src/fintech_agent/tracing.py:39)

---

## 4. Collections & comprehensions

- **`list` `[]`** and **`dict` `{}`** — the workhorses. A `messages` list of
  role/content dicts is the AI conversation format.
  → [agent.py](src/fintech_agent/agent.py) (the `messages = [ {...}, {...} ]` block in `run`)

- **`.append(x)`** — add to end of a list. **`.get(key, default)`** — safe dict
  read that won't throw on a missing key.
  → [agent.py:61](src/fintech_agent/agent.py:61), [knowledge.py:33](src/fintech_agent/knowledge.py:33)

- **List comprehension** — `[f(x) for x in xs if cond]` ≈ LINQ
  `xs.Where(cond).Select(f)`.
  → [knowledge.py:40](src/fintech_agent/knowledge.py:40) (`[(h, b) for h, b in sections if b]`)

- **Generator expression** — same but lazy, no brackets, often inside `join`/`sum`.
  → [knowledge.py:49](src/fintech_agent/knowledge.py:49) (`sum(1 for t in ... if t in ...)`),
  [tracing.py:68](src/fintech_agent/tracing.py:68)

- **Dict as a lookup/dispatch table** — map a string → a function, then call it.
  This is how tools are routed by name.
  → [tools.py:213](src/fintech_agent/tools.py:213) (`_DISPATCH = { "get_account_balance": lambda a: ... }`)

- **Tuple unpacking** — `for name, args in pairs:` splits each pair into two vars.
  → [agent.py:108](src/fintech_agent/agent.py:108)

- **`enumerate`** — loop with an index: `for i, x in enumerate(xs)`.
  → [tracing.py:66](src/fintech_agent/tracing.py:66)

- **`"\n".join(parts)`** — glue a list of strings (like C# `string.Join`).
  → [knowledge.py:58](src/fintech_agent/knowledge.py:58)

- **Slicing / indexing** — `xs[0]` (first), `s[:80]` (first 80 chars),
  `resp.choices[0].message`.
  → [agent.py:116](src/fintech_agent/agent.py:116)

---

## 5. Error handling, context managers, lambdas

- **`try / except`** — like `try / catch`. `except X as e:` binds the exception;
  `raise` re-throws; `continue` inside a loop skips to the next item.
  → [agent.py:166](src/fintech_agent/agent.py:166), [tools.py:230](src/fintech_agent/tools.py:230)

- **`with ... as x:` (context manager)** — like `using` / `IDisposable`. Runs
  setup on entry and cleanup on exit automatically. Here it **times** each stage
  for the trace tree.
  → [agent.py:137](src/fintech_agent/agent.py:137), [agent.py:153](src/fintech_agent/agent.py:153)

- **Writing your own context manager** — `@contextmanager` + `yield` (code before
  `yield` = setup, after = cleanup, in a `finally`).
  → [tracing.py:39](src/fintech_agent/tracing.py:39)

- **`lambda`** — inline anonymous function ≈ `Func<>` / `x => ...`.
  → [agent.py:77](src/fintech_agent/agent.py:77), [knowledge.py:53](src/fintech_agent/knowledge.py:53)

- **`getattr(obj, "x", default)`** — read an attribute safely if you're not sure it
  exists (used to read the API's `usage` object defensively).
  → [cost.py:64](src/fintech_agent/safety/cost.py:64)

---

## 6. C# gotchas to watch for

- **`for ... else:`** — the `else` runs only if the loop finished *without*
  `break`. (A real Python oddity — it's the "couldn't finish" fallback in `run`.)
  → [agent.py:216](src/fintech_agent/agent.py:216)

- **Mutable objects pass by reference** — passing a `list`/`dict` into a function
  and calling `.append()` changes the caller's copy. That's why `tool_calls` and
  `messages` are passed around and mutated in place.
  → [agent.py](src/fintech_agent/agent.py) (`_invoke` appends to the caller's `tool_calls`)

- **No `null`, no `var`, no interfaces needed** — "duck typing": if an object has
  the method you call, it works, regardless of its declared type.

---

## 7. Not core Python, but needed for THIS project

- **`json.loads` / `json.dumps`** — JSON string ⇄ Python dict. Tool arguments
  arrive as JSON *strings* and must be parsed.
  → [agent.py:110](src/fintech_agent/agent.py:110)

- **Regex (`re`)** — compiled patterns for text matching (tool-call recovery,
  PII fallback).
  → [agent.py:27](src/fintech_agent/agent.py:27)

- **Environment variables + `.env`** — config loaded at startup, like
  `appsettings.json`. `os.getenv("KEY", default)`.
  → [config.py:19](src/fintech_agent/config.py:19), [config.py:44](src/fintech_agent/config.py:44)

- **The chat-completions API shape** — `messages` (list of `{role, content}`
  dicts), `resp.choices[0].message`, `.tool_calls`, `.usage`. This is the *AI*
  contract, not Python syntax.
  → [agent.py:153](src/fintech_agent/agent.py:153)

---

## How to use this file
1. Read a row, then **click the line link** to see it in real code.
2. Or open [agent.py](src/fintech_agent/agent.py), set a breakpoint on the
   `STEP 0` line, run **"Debug: CLI one-shot"** (F5), and step with F10 —
   you'll pass through most of these concepts in order in one run.
3. When a line confuses you, find the concept here and read the tiny example.

Suggested order to learn: **§1 → §2 → §3 → §4 → §5**, then the AI bits in §7.
