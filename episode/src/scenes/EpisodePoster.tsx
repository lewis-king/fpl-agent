import episodeData from '../data/episode-data.json';
import {BrandMark, palette, TeamPitch} from '../components';
import type {EpisodeData} from '../types';

const data = episodeData as EpisodeData;
const winner = data.tournament.contestants.find((contestant) => contestant.candidateId === data.decision.candidateId);
const contenders = Array.from({length: 38}, (_, index) =>
  data.tournament.contestants[(index * 37 + 11) % data.tournament.contestants.length],
);

const tone = (candidateId: string) => {
  const seed = Number.parseInt(candidateId.slice(-6), 16);
  const tones = ['#82ad8a', '#c79758', '#7193a7', '#a96e61'];
  return tones[seed % tones.length];
};

export const EpisodePoster = () => (
  <div className="episode-canvas" style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
    <div className="episode-grid" />
    <div style={{position: 'absolute', inset: 18, border: '1px solid rgba(239,244,237,.12)', borderRadius: 38}} />

    <div style={{position: 'absolute', left: 76, top: 64, zIndex: 6, display: 'flex', alignItems: 'center', gap: 17}}>
      <BrandMark dark />
      <div>
        <div style={{fontSize: 17, fontWeight: 680}}>FPLAgent</div>
        <div className="mono" style={{marginTop: 4, color: palette.muted, fontSize: 10, letterSpacing: '.13em'}}>THE DECISION TOURNAMENT · 2026–27</div>
      </div>
    </div>

    <div style={{position: 'absolute', left: 76, top: 214, zIndex: 5, width: 630}}>
      <div className="mono" style={{color: palette.green, fontSize: 12, fontWeight: 800, letterSpacing: '.18em'}}>THE SQUAD KNOCKOUT</div>
      <h1 style={{margin: '22px 0 20px', fontSize: 102, fontWeight: 635, lineHeight: .86, letterSpacing: '-.076em'}}>
        551,829<br />enter.
      </h1>
      <div style={{color: palette.muted, fontSize: 34, fontWeight: 520, lineHeight: 1.15, letterSpacing: '-.035em'}}>Every legal squad gets a call sign.<br />Every test sends more home.</div>
      <div style={{display: 'flex', alignItems: 'center', gap: 17, marginTop: 54}}>
        <div style={{width: 78, height: 2, background: palette.green}} />
        <div className="mono" style={{color: palette.muted, fontSize: 10, letterSpacing: '.15em'}}>QUALIFY · SURVIVE · DEFEND · WIN</div>
      </div>
    </div>

    <div style={{position: 'absolute', left: 725, top: 160, zIndex: 2, width: 480, height: 780}}>
      {contenders.map((contestant, index) => {
        const row = Math.floor(index / 4);
        const column = index % 4;
        const squeeze = row / 10;
        return (
          <div
            key={`${contestant.candidateId}-${index}`}
            style={{
              position: 'absolute',
              left: column * 110 + squeeze * 58,
              top: row * 75,
              width: 142 - squeeze * 36,
              height: 58,
              overflow: 'hidden',
              borderRadius: 11,
              borderLeft: `4px solid ${tone(contestant.candidateId)}`,
              opacity: 0.88 - squeeze * 0.48,
              transform: `rotate(${(column - 1.5) * 0.8 + row * 0.09}deg)`,
              background: '#1b2720',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,.08)',
            }}
          >
            <div style={{padding: '10px 10px 0', overflow: 'hidden', color: palette.paper, fontSize: 11, fontWeight: 720, textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{contestant.callSign}</div>
            <div className="mono" style={{padding: '7px 10px', color: 'rgba(239,244,237,.4)', fontSize: 7, letterSpacing: '.06em'}}>{contestant.formation} · {contestant.captain}</div>
          </div>
        );
      })}
      <div style={{position: 'absolute', left: 228, top: 718, width: 2, height: 104, background: `linear-gradient(${palette.green}, transparent)`}} />
    </div>

    <div style={{position: 'absolute', right: 58, top: 103, zIndex: 4, width: 710, textAlign: 'right'}}>
      <div className="mono" style={{color: palette.green, fontSize: 13, fontWeight: 800, letterSpacing: '.18em'}}>ONE SURVIVES</div>
      <div style={{marginTop: 8, fontSize: 78, fontWeight: 660, lineHeight: .9, letterSpacing: '-.068em'}}>{data.decision.callSign}</div>
    </div>
    <div style={{position: 'absolute', right: -68, top: 238, zIndex: 3, transform: 'rotate(1.8deg) scale(.72)', transformOrigin: 'top right'}}>
      <TeamPitch data={data} />
    </div>
    <div style={{position: 'absolute', right: 80, bottom: 61, zIndex: 6, display: 'flex', alignItems: 'center', gap: 30}}>
      {[
        ['SHAPE', data.decision.formation],
        ['CAPTAIN', data.decision.captain],
        ['FINAL REGRET', winner?.synthesisRegret?.toFixed(3) ?? 'WINNER'],
      ].map(([label, value]) => (
        <div key={label} style={{minWidth: 115, paddingTop: 12, borderTop: '1px solid rgba(239,244,237,.15)'}}>
          <div className="mono" style={{color: palette.muted, fontSize: 8, letterSpacing: '.14em'}}>{label}</div>
          <div style={{marginTop: 6, fontSize: 17, fontWeight: 680}}>{value}</div>
        </div>
      ))}
    </div>
    <div style={{position: 'absolute', left: 18, right: 18, bottom: 18, height: 9, borderRadius: '0 0 28px 28px', background: palette.greenDark}} />
  </div>
);
