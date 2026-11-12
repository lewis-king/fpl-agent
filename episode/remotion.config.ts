import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setPixelFormat('yuv420p');
Config.setConcurrency(8);
Config.setChromiumOpenGlRenderer('angle');
