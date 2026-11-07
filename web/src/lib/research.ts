// Entry point to the research logic ported verbatim from the old frontend.
// Pages import from here, never from ./legacy directly, so the legacy modules can
// be replaced one function at a time with typed TypeScript later.
//
// The legacy modules are plain JavaScript whose inferred types are narrower than
// the data they actually accept (for example normalizers that may return null),
// so each module is exposed as a loosely typed namespace. Replacing a function
// with typed TypeScript is the way to tighten it.
import * as sectorResearchModule from './legacy/sector-research.js';
import * as sectorScarcityModule from './legacy/sector-scarcity.js';
import * as sectorHistoryModule from './legacy/sector-history.js';
import * as subscriptionsModule from './legacy/ai-subscription.js';
import * as reviewModule from './legacy/research-review.js';
import * as cycleModule from './legacy/research-cycle.js';

/* eslint-disable @typescript-eslint/no-explicit-any */
type LegacyModule = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

export const sectorResearch: LegacyModule = sectorResearchModule;
export const sectorScarcity: LegacyModule = sectorScarcityModule;
export const sectorHistory: LegacyModule = sectorHistoryModule;
export const subscriptions: LegacyModule = subscriptionsModule;
export const review: LegacyModule = reviewModule;
export const cycle: LegacyModule = cycleModule;
