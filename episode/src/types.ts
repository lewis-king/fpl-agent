export type Player = {
  element: number;
  name: string;
  position: 'GK' | 'DEF' | 'MID' | 'FWD';
  price: number;
  team: string;
  captain: boolean;
  viceCaptain: boolean;
};

export type TournamentContestant = {
  candidateId: string;
  callSign: string;
  callNote: string;
  formation: string;
  benchSpend: number;
  proxyScore: number;
  captain: string;
  viceCaptain: string;
  expectedPoints: number;
  originIds: string[];
  players: string[];
  starters: Player[];
  bench: Player[];
  robustFinalist: boolean;
  robustRegret: number | null;
  horizonFinalist: boolean;
  horizonRegret: number | null;
  synthesisRank: number | null;
  synthesisRegret: number | null;
  champion: boolean;
};

export type EpisodeData = {
  generatedAt: string;
  decision: {
    candidateId: string;
    callSign: string;
    callNote: string;
    fingerprint: string;
    formation: string;
    captain: string;
    viceCaptain: string;
    budget: number;
    benchSpend: number;
    starters: Player[];
    bench: Player[];
  };
  search: {
    players: number;
    playerEvents: number;
    seeds: number;
    oneSwap: number;
    local: number;
    distantMilp: number;
    evolution: number;
    universe: number;
    discovery: number;
    residual: number;
    finalists: number;
    proxyScenarios: number;
    screenWorlds: number;
    selectionWorlds: number;
    holdoutWorlds: number;
    stressWorlds: number;
    leader: string;
    leaderCallSign: string;
  };
  horizon: {
    challengers: number;
    protectedNeighbours: number;
    finalists: number;
    policySolves: number;
    leader: string;
    leaderCallSign: string;
    verdict: string;
    centralDelta: number;
  };
  synthesis: {
    selectedRegret: number;
    ranking: Array<{
      rank: number;
      candidateId: string;
      formation: string;
      fiveWeekRegret: number;
      eightWeekRegret: number;
      synthesisRegret: number;
      callSign: string;
      callNote: string;
      players: string[];
    }>;
    weightIntervals: Array<{
      candidate_id: string;
      lower: number;
      upper: number;
      midpoint_regret: number;
    }>;
    verdict: string;
  };
  tournament: {
    rounds: Array<{
      label: string;
      entrants: number;
      survivors: number;
    }>;
    contestants: TournamentContestant[];
    captainDiversity: TournamentContestant[];
    spotlights: TournamentContestant[];
    synthesisFinalists: TournamentContestant[];
    diversity: {
      deepFinalists: number;
      distinctCaptains: number;
      captainCounterfactuals: number;
      noMeanLeaderFinalists: number;
      guardPassed: boolean;
    };
  };
  gates: {
    structure: {
      candidates: number;
      views: number;
      leader: string;
      verdict: string;
      supportedReversal: boolean;
    };
    role: {
      candidates: number;
      scenarios: number;
      verdict: string;
      supportedReversals: number;
    };
    availability: {
      selected: number;
      clear: number;
      verify: number;
      officialAttention: number;
      current: boolean;
    };
  };
  performance: {
    totalWallSeconds: number;
    stages: Array<{
      name: string;
      wallSeconds: number;
      averageCpuCores: number;
    }>;
    acceleration: {
      gpu: string;
      initialSerialSeconds: number;
      initialParallelSeconds: number;
      roleSerialSeconds: number;
      roleParallelSeconds: number;
      roleAverageCores: number;
    };
  };
};
