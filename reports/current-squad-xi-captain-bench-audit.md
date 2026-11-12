# Simulation-authoritative XI, captain and bench audit

Verdict: **simulation_champion_promoted_after_independent_holdout**.
Production changed: **True**.
Publishable: **True**.

This checksum-bound audit never replaces the selected 15. It exhaustively selects the actionable XI, all three outfield substitute positions, captain and vice-captain using residual and explicit football-component simulations.

## Published configuration

- Formation: 3-4-3
- Captain / vice: Bruno Fernandes / Lacroix
- XI: Donnarumma, Lacroix, Tarkowski, Maguire, Bruno Fernandes, Mbeumo, Semenyo, Szoboszlai, Igor Thiago, Calvert-Lewin, Richarlison
- Bench order: Truffert, N.Williams, Gakpo, Verbruggen

## Resolved configuration champion

- Formation: 4-4-2
- Captain / vice: Bruno Fernandes / Lacroix
- XI: Igor Thiago, Lacroix, Tarkowski, Calvert-Lewin, Szoboszlai, Donnarumma, Semenyo, Maguire, Bruno Fernandes, Mbeumo, N.Williams
- Bench order: Richarlison, Truffert, Gakpo, Verbruggen

## Independent holdout difference versus published

| Family | Mean | 95% CI | Beat probability |
| --- | ---: | ---: | ---: |
| Residual | -0.274 | [-0.297, -0.252] | 31.2% |
| Component | +0.660 | [+0.606, +0.713] | 46.5% |

## Coverage

- Legal XIs: 550
- Bench orders scored: 3300
- Joint configurations scored: 4951
- Holdout finalists: 64
- Independent holdout champion: XI-60ce4f7bfef5 (stable: True)
- Holdout robust gain: +0.237

Never alter the selected 15 here. Select XI, bench priority, captain and vice by minimax regret across residual and explicit football-component simulations. Promote only when the preselected champion remains the independent holdout champion, or when both samples agree on captain and differ only between top-three vice-captains, orderings of the same bench, or one starter/bench swap within 0.0125 regret in both samples. Resolve that narrow single-action equivalence class using all simulated worlds. Every captain or multi-player XI disagreement fails closed.
