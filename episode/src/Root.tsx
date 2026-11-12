import {Composition, Still} from 'remotion';
import {FPL_AGENT_KNOCKOUT_FRAMES, FplKnockoutEpisode} from './FplKnockoutEpisode';
import {EpisodePoster} from './scenes/EpisodePoster';

export const RemotionRoot = () => (
  <>
    <Composition
      id="FPLAgentDecision"
      component={FplKnockoutEpisode}
      durationInFrames={FPL_AGENT_KNOCKOUT_FRAMES}
      fps={30}
      width={1920}
      height={1080}
    />
    <Still
      id="FPLAgentDecisionPoster"
      component={EpisodePoster}
      width={1920}
      height={1080}
    />
  </>
);
