"""Run the defective-delivery scenario end to end:  python demo.py"""

from ai import FakeLLM, SuggestionLog
from coordinator import Coordinator
from scenario import torre_norte


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> None:
    site = torre_norte()
    log = SuggestionLog()
    coord = Coordinator(site, FakeLLM(), log)

    section("1. Field signal (voice note + 2 photos from the almacenista)")
    report = "Llegaron las 40 toneladas de varilla de la PO-1182, como 3 vienen dobladas y oxidadas"
    print(f'"{report}"')

    section("2. AI perception -> guardrail")
    facts = coord.read_field_report(report, ["IMG_0412.jpg", "IMG_0413.jpg"], "PO-1182/1")
    print(f"Read: delivered={facts.delivered} t, defective={facts.defective} t "
          f"({facts.defect}), confidence={facts.confidence}")
    if facts.needs_confirmation:
        print("Needs a one-tap confirmation because:", "; ".join(facts.reasons))
        print("Supervisor counts the bundles and confirms: 3 t defective.")

    section("3. Deterministic commands (system of record)")
    out = coord.confirm_receipt(facts, defective=3, photos=["IMG_0412.jpg", "IMG_0413.jpg"])
    for e in out.events:
        print(f"{e.kind:22} {e.data}")
    print(f"Inventory now: {site.inventory}")

    section("4. Impact: what this rejection breaks")
    for s in out.shortfalls:
        print(f"'{site.tasks[s.task_id].name}' needs {s.needed} t, has {s.available} t "
              f"-> short {s.gap} t, needed on site by {s.needed_on:%d/%m}")

    section("5. Options with computed consequences (ranked)")
    for i, c in enumerate(out.options, 1):
        print(f"{i}. {c.title}")
        print(f"   cash out {c.cash_out} MXN | net cost {c.net_cost} MXN | delay {c.delay_days} d"
              f" | shifts {list(c.shifted_tasks) or '-'}")
        print(f"   budget after: {', '.join(f'{k} {v}%' for k, v in c.budget_after.items())}"
              f" | approvals: {', '.join(c.approvals) or 'none'}"
              f" | decide by: {c.decide_by or '-'}")
        for n in c.notes:
            print(f"   note: {n}")
    print(f"\nAI explanation for the residente:\n  {out.explanation}")

    section("6. Coordination: who hears what")
    for m in out.messages:
        tag = " (template fallback)" if m.fallback_used else ""
        print(f"-> {m.to.name} via {m.to.channel} [{m.status}]{tag}\n   {m.text}\n")

    section("7. What the supervisor should do next")
    for i, step in enumerate(out.next_steps, 1):
        print(f"{i}. {step}")

    section('8. Supervisor asks: "¿Y si usamos las varillas dañadas?"')
    answer = coord.what_if("¿Y si usamos las varillas dañadas?", out.shortfalls[0])
    print(answer if isinstance(answer, str) else f"BLOCKED: {answer.blocked}")

    section("9. Audit log (feeds the acceptance-rate metric)")
    for s in log.items:
        print(f"{s.task:15} valid={s.valid} fallback={s.fallback_used} human={s.human_decision}")
    print(f"perception acceptance rate: {log.acceptance_rate('perception')}")


if __name__ == "__main__":
    main()
