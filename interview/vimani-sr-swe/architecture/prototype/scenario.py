"""Seed data for the 'defective rebar delivery' scenario. All figures are illustrative."""

from datetime import date

from domain import D, Contact, Offer, POLine, Site, Task


def torre_norte() -> Site:
    return Site(
        name="Torre Norte",
        today=date(2026, 10, 19),
        inventory={"varilla 3/8": D(0)},
        po_lines={
            "PO-1182/1": POLine("PO-1182/1", "Aceros del Bajío", "varilla 3/8", "t",
                                ordered=D(40), unit_price=D(21500), cost_code="03.02.010"),
        },
        tasks={
            "ARM-N4": Task("ARM-N4", "Armado de acero losa N4", date(2026, 10, 21),
                           needs={"varilla 3/8": D(38)}, successors=["COL-N4"],
                           split_extra_cost=D(9500), split_requires=("residente", "DRO"),
                           foreman="foreman"),
            "COL-N4": Task("COL-N4", "Colado losa N4", date(2026, 10, 22),
                           successors=["CIM-N5"], rebooking_fee=D(8000)),
            "CIM-N5": Task("CIM-N5", "Cimbra losa N5", date(2026, 10, 23)),
        },
        offers=[
            Offer("Aceros del Bajío", "varilla 3/8", D(21500), lead_days=3),
            Offer("Ferretera Hidalgo", "varilla 3/8", D(25370), lead_days=0),
        ],
        contacts={
            "supplier": Contact("supplier", "Aceros del Bajío — ventas", "email", external=True),
            "compras": Contact("compras", "Laura (compras)", "app"),
            "cuentas_por_pagar": Contact("cuentas_por_pagar", "Tesorería", "app"),
            "residente": Contact("residente", "Ing. Ramírez (residente)", "app"),
            "foreman": Contact("foreman", "Don Chuy (cabo de fierreros)", "whatsapp"),
            "DRO": Contact("DRO", "Arq. Medina (DRO)", "email", external=True),
        },
        budget={"03.02.010": D(900000), "01.05": D(2100000)},
        exposure={"03.02.010": D(860000), "01.05": D(1980000)},
        daily_indirect_cost=D(35000),
        indirect_cost_code="01.05",
    )
