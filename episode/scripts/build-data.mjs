import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const episodeRoot = resolve(here, '..');
const repoRoot = resolve(episodeRoot, '..');

const readJson = async (path) =>
  JSON.parse(await readFile(resolve(repoRoot, path), 'utf8'));

const pipeline = await readJson('data/manifests/fpl-gw1-deadline-pipeline.json');
const robust = await readJson('data/model/robust_search_v2_global/results.json');
const horizon = await readJson('data/model/horizon_audit_v1/results.json');
const synthesis = await readJson('data/model/gw1_decision_synthesis_v1/results.json');
const structure = await readJson('data/model/gw1_structure_stress_v1/results.json');
const role = await readJson('data/model/preseason_role_scenario_v1/results.json');
const availability = await readJson('data/manifests/fpl-availability-watch.json');
const shortlist = await readJson('data/model/robust_search_v2_global/shortlist.json');
const currentSnapshot = await readJson('data/manifests/fpl-current-snapshot.json');
const bootstrap = await readJson(
  `data/raw/fpl/2026-27/snapshots/live/${currentSnapshot.snapshot_id}/bootstrap-static.json`,
);

const displayNameOverrides = new Map([
  [426, 'Bruno Fernandes'],
  [106, 'Igor Thiago'],
]);
const elementNames = new Map(
  bootstrap.elements.map((element) => [
    Number(element.id),
    displayNameOverrides.get(Number(element.id)) ?? String(element.web_name),
  ]),
);
const teamNames = new Map(
  bootstrap.teams.map((team) => [Number(team.id), String(team.name)]),
);
const positionNames = new Map([
  [1, 'GK'],
  [2, 'DEF'],
  [3, 'MID'],
  [4, 'FWD'],
]);
const elementsById = new Map(
  bootstrap.elements.map((element) => [Number(element.id), element]),
);
const candidatesById = new Map(
  shortlist.candidates.map((candidate) => [String(candidate.candidate_id), candidate]),
);
const winningElements = new Set(synthesis.decision.candidate.selected.map(Number));
const genericSuffixes = [
  'Switch',
  'Pivot',
  'Route',
  'Balance',
  'Press',
  'Arc',
  'Wall',
  'Engine',
  'Shield',
  'Circuit',
  'Break',
  'Front',
];

const hashText = (value) =>
  [...String(value)].reduce((hash, character) => ((hash * 33) ^ character.charCodeAt(0)) >>> 0, 5381);

const playerForElement = (element, lineup) => {
  const raw = elementsById.get(Number(element));
  const id = Number(element);
  return {
    element: id,
    name: elementNames.get(id) ?? `#${id}`,
    position: positionNames.get(Number(raw?.element_type)) ?? 'MID',
    price: Number(raw?.now_cost ?? 0) / 10,
    team: teamNames.get(Number(raw?.team)) ?? 'Unknown',
    captain: Number(lineup?.captain) === id,
    viceCaptain: Number(lineup?.vice_captain) === id,
  };
};

const squadForCandidate = (candidate) => {
  const lineup = candidate?.lineups?.['1'];
  if (!lineup) return {starters: [], bench: []};
  return {
    starters: lineup.starters.map((element) => playerForElement(element, lineup)),
    bench: lineup.bench_order.map((element) => playerForElement(element, lineup)),
  };
};

const identityFor = (row, index) => {
  const candidate = candidatesById.get(String(row.candidate_id));
  const elements = (candidate?.selected ?? []).map(Number);
  const names = elements.map((element) => elementNames.get(element) ?? `#${element}`);
  const distinctive = elements
    .filter((element) => !winningElements.has(element))
    .map((element) => elementNames.get(element) ?? `#${element}`);
  if (row.candidate_id === synthesis.decision.candidate_id) {
    return {
      callSign: 'The Mbeumo Redline',
      callNote: 'Mbeumo · Bruno · Semenyo core',
      players: names,
    };
  }
  if (row.candidate_id === robust.leader.candidate_id) {
    return {
      callSign: 'The Mbeumo Vanguard',
      callNote: distinctive.slice(0, 3).join(' · ') || names.slice(0, 3).join(' · '),
      players: names,
    };
  }
  if (row.candidate_id === horizon.leader.candidate_id) {
    return {
      callSign: 'The Eight-Week Relay',
      callNote: distinctive.slice(0, 3).join(' · ') || names.slice(0, 3).join(' · '),
      players: names,
    };
  }
  if (row.candidate_id === structure.stress_leader_id) {
    return {
      callSign: 'The GW1 Sprinter',
      callNote: distinctive.slice(0, 3).join(' · ') || names.slice(0, 3).join(' · '),
      players: names,
    };
  }
  const captain = elementNames.get(Number(row.lineups?.['1']?.captain ?? 0));
  const isCaptainCounterfactual = (row.origin_ids ?? []).some((origin) => String(origin).startsWith('captain-counterfactual-'));
  const anchor = (isCaptainCounterfactual ? captain : null) ?? distinctive[0] ?? captain ?? names[index % Math.max(1, names.length)] ?? 'Squad';
  return {
    callSign: `The ${anchor} ${genericSuffixes[hashText(row.candidate_id) % genericSuffixes.length]}`,
    callNote: distinctive.slice(0, 3).join(' · ') || names.slice(0, 3).join(' · '),
    players: names,
  };
};

const contestantIdentities = new Map(
  shortlist.candidates.map((row, index) => [String(row.candidate_id), identityFor(row, index)]),
);
const selectedIdentity = contestantIdentities.get(String(synthesis.decision.candidate_id));
const robustMetrics = new Map(
  robust.finalist_metrics.map((row) => [String(row.candidate_id), row]),
);
const horizonMetrics = new Map(
  horizon.finalist_metrics.map((row) => [String(row.candidate_id), row]),
);
const synthesisMetrics = new Map(
  synthesis.ranking.map((row) => [String(row.candidate_id), row]),
);

const squad = synthesis.decision.squad;
const player = (row) => ({
  element: row.element,
  name: row.name,
  position: row.position,
  price: row.price,
  team: row.team,
  captain: Boolean(row.captain),
  viceCaptain: Boolean(row.vice_captain),
});

const output = {
  generatedAt: new Date().toISOString(),
  decision: {
    candidateId: synthesis.decision.candidate_id,
    callSign: selectedIdentity?.callSign ?? 'The Selected XI',
    callNote: selectedIdentity?.callNote ?? 'published synthesis winner',
    fingerprint: pipeline.input_fingerprint,
    formation: synthesis.decision.formation,
    captain: squad.starters.find((row) => row.captain)?.name ?? 'Unknown',
    viceCaptain: squad.starters.find((row) => row.vice_captain)?.name ?? 'Unknown',
    budget: squad.budget_spent,
    benchSpend: synthesis.decision.candidate.gw1_bench_spend,
    starters: squad.starters.map(player),
    bench: squad.bench.map(player),
  },
  search: {
    players: robust.diagnostics.component_holdout.players,
    playerEvents: robust.diagnostics.component_holdout.component_event_models.rows,
    seeds: robust.funnel.seed_squads,
    oneSwap: robust.funnel.one_swap_universe,
    local: robust.funnel.local_two_swap_universe,
    distantMilp: robust.funnel.global_milp_squads,
    evolution: robust.funnel.global_evolution_squads,
    universe: robust.funnel.combined_universe,
    discovery: robust.funnel.discovery_candidates,
    residual: robust.funnel.shortlist,
    finalists: robust.funnel.finalists,
    proxyScenarios: robust.funnel.proxy_scenarios,
    screenWorlds: robust.funnel.screen_simulations,
    selectionWorlds: robust.funnel.selection_simulations,
    holdoutWorlds: robust.funnel.holdout_simulations,
    stressWorlds: robust.funnel.stress_simulations,
    leader: robust.leader.candidate_id,
    leaderCallSign: contestantIdentities.get(String(robust.leader.candidate_id))?.callSign,
  },
  horizon: {
    challengers: horizon.funnel.horizon_specific_candidates,
    protectedNeighbours: horizon.funnel.protected_horizon_neighbours,
    finalists: horizon.funnel.deep_finalists,
    policySolves: horizon.funnel.deep_finalists * 2,
    leader: horizon.leader.candidate_id,
    leaderCallSign: contestantIdentities.get(String(horizon.leader.candidate_id))?.callSign,
    verdict: horizon.verdict,
    centralDelta: synthesis.long_horizon_challenger.central_eight_week_delta.mean_delta,
  },
  synthesis: {
    selectedRegret: synthesis.decision.synthesis_regret,
    ranking: synthesis.ranking.slice(0, 10).map((row) => ({
      rank: row.rank,
      candidateId: row.candidate_id,
      formation: row.gw1_formation,
      fiveWeekRegret: row.robust_family_regret,
      eightWeekRegret: row.horizon_family_regret,
      synthesisRegret: row.synthesis_regret,
      ...contestantIdentities.get(String(row.candidate_id)),
    })),
    weightIntervals: synthesis.horizon_weight_champion_intervals,
    verdict: synthesis.verdict,
  },
  tournament: {
    rounds: [
      {label: 'Legal universe', entrants: robust.funnel.combined_universe, survivors: robust.funnel.discovery_candidates},
      {label: 'Multi-objective qualifier', entrants: robust.funnel.discovery_candidates, survivors: robust.funnel.shortlist},
      {label: 'Component knockout', entrants: robust.funnel.shortlist, survivors: robust.funnel.finalists},
      {label: 'Horizon challenge', entrants: horizon.funnel.combined_candidates, survivors: horizon.funnel.deep_finalists},
      {label: 'Shared synthesis field', entrants: synthesis.candidate_coverage.common_finalists, survivors: 8},
      {label: 'Publication final', entrants: 8, survivors: 1},
    ],
    contestants: shortlist.candidates.map((candidate, index) => {
      const id = String(candidate.candidate_id);
      const identity = contestantIdentities.get(id);
      const robustMetric = robustMetrics.get(id);
      const horizonMetric = horizonMetrics.get(id);
      const synthesisMetric = synthesisMetrics.get(id);
      const captainElement = Number(candidate.lineups?.['1']?.captain ?? 0);
      const viceCaptainElement = Number(candidate.lineups?.['1']?.vice_captain ?? 0);
      const squad = squadForCandidate(candidate);
      return {
        candidateId: id,
        callSign: identity?.callSign ?? `The Qualifier ${String(index + 1).padStart(3, '0')}`,
        callNote: identity?.callNote ?? candidate.display_name,
        formation: candidate.gw1_formation,
        benchSpend: candidate.gw1_bench_spend,
        proxyScore: candidate.proxy_score,
        captain: elementNames.get(captainElement) ?? 'Unknown',
        viceCaptain: elementNames.get(viceCaptainElement) ?? 'Unknown',
        expectedPoints: Number(candidate.lineups?.['1']?.expected_points ?? 0),
        originIds: candidate.origin_ids ?? [],
        players: identity?.players ?? [],
        starters: squad.starters,
        bench: squad.bench,
        robustFinalist: Boolean(robustMetric),
        robustRegret: robustMetric?.robust_regret ?? null,
        horizonFinalist: Boolean(horizonMetric),
        horizonRegret: horizonMetric?.robust_regret ?? null,
        synthesisRank: synthesisMetric?.rank ?? null,
        synthesisRegret: synthesisMetric?.synthesis_regret ?? null,
        champion: id === synthesis.decision.candidate_id,
      };
    }),
  },
  gates: {
    structure: {
      candidates: structure.ranking.length,
      views: 5,
      leader: structure.stress_leader_id,
      verdict: structure.verdict,
      supportedReversal: structure.supported_reversal,
    },
    role: {
      candidates: role.candidate_squads,
      scenarios: Object.keys(role.scenarios).length,
      verdict: role.verdict,
      supportedReversals: role.supported_deep_squad_scenarios.length,
    },
    availability: {
      selected: availability.summary.selected_players,
      clear: availability.summary.no_attention,
      verify: availability.summary.role_verification,
      officialAttention: availability.summary.official_attention,
      current: availability.current,
    },
  },
  performance: {
    totalWallSeconds: pipeline.stages.reduce(
      (sum, stage) => sum + (stage.performance?.wall_seconds ?? 0),
      0,
    ),
    stages: pipeline.stages.map((stage) => ({
      name: stage.name,
      wallSeconds: stage.performance?.wall_seconds ?? 0,
      averageCpuCores: stage.performance?.average_cpu_cores ?? 0,
    })),
    acceleration: {
      gpu: 'NVIDIA GeForce RTX 5090',
      initialSerialSeconds: 152.999,
      initialParallelSeconds: 23.519,
      roleSerialSeconds: 639.824,
      roleParallelSeconds: 198.629,
      roleAverageCores: 3.38,
    },
  },
};

const allContestants = output.tournament.contestants;
const deepContestants = allContestants
  .filter((row) => row.robustFinalist)
  .sort((left, right) => (left.robustRegret ?? 999) - (right.robustRegret ?? 999));
const captainDiversity = [];
const seenCaptains = new Set();
for (const contestant of deepContestants) {
  if (seenCaptains.has(contestant.captain)) continue;
  captainDiversity.push(contestant);
  seenCaptains.add(contestant.captain);
}
const haaland = deepContestants.find((row) => row.captain === 'Haaland');
const champion = allContestants.find((row) => row.champion);
const synthesisFinalists = allContestants
  .filter((row) => row.synthesisRank !== null && row.synthesisRank <= 8)
  .sort((left, right) => left.synthesisRank - right.synthesisRank);

output.tournament.captainDiversity = captainDiversity;
output.tournament.spotlights = [
  ...(haaland ? [haaland] : []),
  ...captainDiversity,
  ...(champion ? [champion] : []),
].filter((row, index, rows) => rows.findIndex((candidate) => candidate.candidateId === row.candidateId) === index);
output.tournament.synthesisFinalists = synthesisFinalists;
output.tournament.diversity = {
  deepFinalists: deepContestants.length,
  distinctCaptains: new Set(deepContestants.map((row) => row.captain)).size,
  captainCounterfactuals: robust.diversity?.captain_publication_guard?.explicit_captain_counterfactuals ?? 0,
  noMeanLeaderFinalists: robust.diversity?.captain_publication_guard?.no_incumbent_leader_finalists ?? 0,
  guardPassed: robust.diversity?.captain_publication_guard?.passed ?? false,
};

const outputPath = resolve(episodeRoot, 'src/data/episode-data.json');
await mkdir(dirname(outputPath), {recursive: true});
await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, 'utf8');
console.log(`Built ${outputPath}`);
