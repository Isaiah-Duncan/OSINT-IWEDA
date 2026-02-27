/**
 * clearance-engine.js
 * Replaces broken clearance computation logic with physics-correct platform evaluation
 * All platforms keyed to ASSETS id field, not ID matching
 * RCS/Altitude/EW as fixed properties, Visual score weather-influenced
 */

// Step 1: Build DOMAIN_LOOKUP keyed to ASSETS IDs
const DOMAIN_LOOKUP = {
  // US Platforms
  "B2": { rcs: 0.98, alt: "very_high", illumSens: "negligible", visualWt: 0.10, ewCapable: true, primaryDomain: "radar" },
  "F22": { rcs: 0.95, alt: "very_high", illumSens: "low", visualWt: 0.15, ewCapable: true, primaryDomain: "radar" },
  "F35": { rcs: 0.90, alt: "very_high", illumSens: "low", visualWt: 0.20, ewCapable: true, primaryDomain: "radar" },
  "F15": { rcs: 0.40, alt: "high", illumSens: "moderate", visualWt: 0.35, ewCapable: true, primaryDomain: "radar" },
  "F16": { rcs: 0.25, alt: "high", illumSens: "moderate", visualWt: 0.40, ewCapable: true, primaryDomain: "radar" },
  "F18": { rcs: 0.30, alt: "high", illumSens: "moderate", visualWt: 0.40, ewCapable: true, primaryDomain: "radar" },
  "AC130": { rcs: 0.35, alt: "low", illumSens: "critical", visualWt: 0.80, ewCapable: false, primaryDomain: "visual" },
  "A10": { rcs: 0.20, alt: "low", illumSens: "high", visualWt: 0.75, ewCapable: false, primaryDomain: "visual" },
  "B52": { rcs: 0.50, alt: "high", illumSens: "moderate", visualWt: 0.30, ewCapable: true, primaryDomain: "radar" },
  "C130": { rcs: 0.45, alt: "medium", illumSens: "high", visualWt: 0.65, ewCapable: false, primaryDomain: "visual" },
  "AH64": { rcs: 0.15, alt: "low", illumSens: "high", visualWt: 0.70, ewCapable: false, primaryDomain: "visual" },
  "UH60": { rcs: 0.12, alt: "medium", illumSens: "high", visualWt: 0.70, ewCapable: false, primaryDomain: "visual" },
  "JDAM": { rcs: 0.05, alt: "ballistic", illumSens: "moderate", visualWt: 0.50, ewCapable: false, primaryDomain: "visual" },
  "TOMAHAWK": { rcs: 0.08, alt: "medium", illumSens: "moderate", visualWt: 0.45, ewCapable: false, primaryDomain: "visual" },
  "PATRIOT": { rcs: 0.60, alt: "high", illumSens: "low", visualWt: 0.25, ewCapable: true, primaryDomain: "radar" },

  // Russian Platforms
  "SU27": { rcs: 0.35, alt: "high", illumSens: "moderate", visualWt: 0.35, ewCapable: true, primaryDomain: "radar" },
  "SU35": { rcs: 0.40, alt: "high", illumSens: "moderate", visualWt: 0.35, ewCapable: true, primaryDomain: "radar" },
  "MIG29": { rcs: 0.30, alt: "high", illumSens: "moderate", visualWt: 0.40, ewCapable: true, primaryDomain: "radar" },
  "MIG31": { rcs: 0.38, alt: "very_high", illumSens: "moderate", visualWt: 0.30, ewCapable: true, primaryDomain: "radar" },
  "TU95": { rcs: 0.55, alt: "high", illumSens: "moderate", visualWt: 0.35, ewCapable: true, primaryDomain: "radar" },
  "TU160": { rcs: 0.52, alt: "high", illumSens: "moderate", visualWt: 0.35, ewCapable: true, primaryDomain: "radar" },
  "MI28": { rcs: 0.18, alt: "low", illumSens: "high", visualWt: 0.70, ewCapable: false, primaryDomain: "visual" },
  "KA52": { rcs: 0.16, alt: "low", illumSens: "high", visualWt: 0.70, ewCapable: false, primaryDomain: "visual" },
  "IL76": { rcs: 0.50, alt: "medium", illumSens: "high", visualWt: 0.65, ewCapable: false, primaryDomain: "visual" },
  "S400": { rcs: 0.65, alt: "high", illumSens: "low", visualWt: 0.20, ewCapable: true, primaryDomain: "radar" },
  "ISKANDER": { rcs: 0.10, alt: "ballistic", illumSens: "moderate", visualWt: 0.50, ewCapable: false, primaryDomain: "visual" },
  "KH55": { rcs: 0.06, alt: "medium", illumSens: "moderate", visualWt: 0.45, ewCapable: false, primaryDomain: "visual" },

  // Chinese Platforms
  "J10": { rcs: 0.28, alt: "high", illumSens: "moderate", visualWt: 0.40, ewCapable: true, primaryDomain: "radar" },
  "J20": { rcs: 0.92, alt: "very_high", illumSens: "low", visualWt: 0.15, ewCapable: true, primaryDomain: "radar" },
  "WZ10": { rcs: 0.14, alt: "low", illumSens: "high", visualWt: 0.70, ewCapable: false, primaryDomain: "visual" },
  "Z9": { rcs: 0.10, alt: "medium", illumSens: "high", visualWt: 0.70, ewCapable: false, primaryDomain: "visual" },
  "Y8": { rcs: 0.48, alt: "medium", illumSens: "high", visualWt: 0.65, ewCapable: false, primaryDomain: "visual" },
  "HQ9": { rcs: 0.62, alt: "high", illumSens: "low", visualWt: 0.20, ewCapable: true, primaryDomain: "radar" },
  "DF21": { rcs: 0.12, alt: "ballistic", illumSens: "moderate", visualWt: 0.50, ewCapable: false, primaryDomain: "visual" },

  // European Platforms
  "TYPHOON": { rcs: 0.38, alt: "high", illumSens: "moderate", visualWt: 0.35, ewCapable: true, primaryDomain: "radar" },
  "GRIPEN": { rcs: 0.32, alt: "high", illumSens: "moderate", visualWt: 0.38, ewCapable: true, primaryDomain: "radar" },
  "RAFALE": { rcs: 0.36, alt: "high", illumSens: "moderate", visualWt: 0.38, ewCapable: true, primaryDomain: "radar" },
  "APACHE": { rcs: 0.16, alt: "low", illumSens: "high", visualWt: 0.70, ewCapable: false, primaryDomain: "visual" },
  "TORNADO": { rcs: 0.42, alt: "high", illumSens: "moderate", visualWt: 0.35, ewCapable: true, primaryDomain: "radar" },
  "METEOR": { rcs: 0.04, alt: "ballistic", illumSens: "moderate", visualWt: 0.50, ewCapable: false, primaryDomain: "visual" },
  "STORM": { rcs: 0.08, alt: "medium", illumSens: "moderate", visualWt: 0.45, ewCapable: false, primaryDomain: "visual" },

  // Other Platforms
  "GERAN2": { rcs: 0.08, alt: "medium", illumSens: "moderate", visualWt: 0.50, ewCapable: false, primaryDomain: "visual" },
  "YJ12": { rcs: 0.10, alt: "low", illumSens: "moderate", visualWt: 0.55, ewCapable: false, primaryDomain: "visual" },
};

// Step 2: Build fixed property score helpers
function rcsScore(platform) {
  const rcs = DOMAIN_LOOKUP[platform]?.rcs ?? 0.15;
  // Convert RCS to detectability score: lower RCS = higher score (less detectable)
  return 1 - rcs;
}

function altitudeScore(platform) {
  const altBand = DOMAIN_LOOKUP[platform]?.alt ?? "medium";
  const altScores = {
    "very_high": 0.95,
    "high": 0.80,
    "medium": 0.60,
    "low": 0.35,
    "ballistic": 0.75,
  };
  return altScores[altBand] ?? 0.60;
}

function ewScore(platform) {
  const ewCapable = DOMAIN_LOOKUP[platform]?.ewCapable ?? false;
  return ewCapable ? 0.80 : 0.30;
}

function visualScore(platform, illumination, cloudCover) {
  const illumSens = DOMAIN_LOOKUP[platform]?.illumSens ?? "moderate";
  const visualWt = DOMAIN_LOOKUP[platform]?.visualWt ?? 0.40;

  // Illumination sensitivity scaling
  const illumScaling = {
    "negligible": 0.05,
    "low": 0.15,
    "moderate": 0.35,
    "high": 0.65,
    "critical": 0.90,
  };

  const illumMultiplier = illumScaling[illumSens] ?? 0.35;
  const illumImpact = illumination * illumMultiplier;

  // Cloud cover suppression: reduces visual detection effectiveness
  const cloudSuppression = Math.max(0, 1 - cloudCover * 0.5);

  // Visual score = platform visual weight * illumination impact * cloud suppression
  return visualWt * illumImpact * cloudSuppression;
}

// Step 3: Build computeNetClearance function
function computeNetClearance(platformId, illumination, cloudCover, ew_active, radar_active) {
  const lookupEntry = DOMAIN_LOOKUP[platformId];
  if (!lookupEntry) {
    // Fallback for unknown platforms: return simple score
    return 0.35;
  }

  const rcs_score = rcsScore(platformId);
  const altitude_score = altitudeScore(platformId);
  const ew_score = ewScore(platformId);
  const visual_score = visualScore(platformId, illumination, cloudCover);

  // Compute net clearance based on primary detection domain
  let net_clearance = 0;

  if (lookupEntry.primaryDomain === "radar") {
    // Radar-primary: RCS, altitude, and EW avoidance are dominant
    if (radar_active) {
      net_clearance = (rcs_score * 0.40 + altitude_score * 0.30 + ew_score * 0.20) * 0.75 + visual_score * 0.10;
    } else {
      // Radar inactive: rely on EW and visual
      net_clearance = (ew_score * 0.40 + altitude_score * 0.20 + visual_score * 0.40);
    }
  } else {
    // Visual-primary: illumination sensitivity is dominant
    if (ew_active && lookupEntry.ewCapable) {
      // EW available and platform has capability
      net_clearance = (visual_score * 0.50 + ew_score * 0.30 + altitude_score * 0.20);
    } else {
      // Rely on visual concealment and altitude
      net_clearance = (visual_score * 0.60 + altitude_score * 0.30 + rcs_score * 0.10);
    }
  }

  return Math.max(0, Math.min(1.0, net_clearance));
}

// Step 4: Build scoreToStatus and scoreToClearance mappers
function scoreToStatus(score) {
  if (score >= 0.80) return "GREEN";
  if (score >= 0.50) return "AMBER";
  return "RED";
}

function scoreToClearance(score) {
  if (score >= 0.80) return "CLEARED";
  if (score >= 0.60) return "PARTIALLY CLEARED";
  if (score >= 0.40) return "MARGINAL";
  if (score >= 0.20) return "RESTRICTED";
  return "FULLY GROUNDED";
}

// Step 5: Build evaluatePlatform function as single public interface
function evaluatePlatform(platform, conditions) {
  // Simple wrapper that just returns the basic computed score
  // Hard constraints checking is done in the calling code (evalCell)
  const platformId = typeof platform === 'string' ? platform : platform.id;

  const illumination = conditions?.illumination ?? 40;
  const cloudCover = conditions?.cloudCover ?? 50;
  const ew_active = conditions?.ew_active ?? false;
  const radar_active = conditions?.radar_active ?? true;

  const score = computeNetClearance(platformId, illumination, cloudCover, ew_active, radar_active);

  return {
    platform: platformId,
    net_clearance: Math.round(score * 100) / 100,
    status: scoreToStatus(score),
    clearanceLabel: scoreToClearance(score),
  };
}

// Step 6: Export public API
window.ClearanceEngine = {
  evaluatePlatform: evaluatePlatform,
  computeNetClearance: computeNetClearance,
  scoreToStatus: scoreToStatus,
  scoreToClearance: scoreToClearance,
  rcsScore: rcsScore,
  altitudeScore: altitudeScore,
  ewScore: ewScore,
  visualScore: visualScore,
  DOMAIN_LOOKUP: DOMAIN_LOOKUP,
};
