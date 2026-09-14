/* Burh engine - browser port.
 *
 * A faithful port of the Python engine in burh/. The two are cross-checked
 * against each other by web/crossvalidate.mjs over randomised cases; any
 * divergence beyond 1e-9 is a build failure.
 *
 * Everything internal is SI: m, kN, kPa, kN/m3. Conversion happens only at
 * the boundary, exactly as in the Python.
 */
const Burh = (function () {
  "use strict";

  // ---- constants (exact) --------------------------------------------------
  const FT_TO_M = 0.3048;
  const IN_TO_M = 0.0254;
  const KIP_TO_KN = 4.4482216152605;
  const KSF_TO_KPA = KIP_TO_KN / (FT_TO_M * FT_TO_M);
  const PCF_TO_KNM3 = (KIP_TO_KN / 1000.0) / (FT_TO_M ** 3);
  const P_ATM_KPA = 101.325;
  const GAMMA_WATER = 9.81;
  const GAMMA_CONCRETE = 23.6;
  const N_C_PHI_ZERO = Math.PI + 2.0;

  const UNITS = {
    SI: { length: 1, force: 1, stress: 1, unitWeight: 1, settle: 1000,
          labels: { length: "m", force: "kN", stress: "kPa", unitWeight: "kN/m³",
                    moment: "kN·m", small: "mm" } },
    US: { length: FT_TO_M, force: KIP_TO_KN, stress: KSF_TO_KPA,
          unitWeight: PCF_TO_KNM3, settle: 1 / IN_TO_M,
          labels: { length: "ft", force: "kip", stress: "ksf", unitWeight: "pcf",
                    moment: "kip·ft", small: "in" } },
  };

  function units(system) {
    const f = UNITS[system];
    if (!f) throw new Error(`Unknown unit system ${system}`);
    return {
      system,
      labels: f.labels,
      toLength: v => v * f.length,
      toForce: v => v * f.force,
      toStress: v => v * f.stress,
      toUnitWeight: v => v * f.unitWeight,
      toMoment: v => v * f.force * f.length,
      toSettle: v => v / f.settle,
      fromLength: v => v / f.length,
      fromForce: v => v / f.force,
      fromStress: v => v / f.stress,
      fromUnitWeight: v => v / f.unitWeight,
      fromMoment: v => v / (f.force * f.length),
      fromSettle: v => v * f.settle,
    };
  }

  const rad = d => (d * Math.PI) / 180.0;
  const deg = r => (r * 180.0) / Math.PI;

  // ---- soil ---------------------------------------------------------------
  const ALPHA_E = { sand_with_fines: 5.0, clean_sand_nc: 10.0, clean_sand_oc: 15.0 };
  const SIGMA_V_FLOOR_KPA = 25.0;
  const PHI_CAP_DEG = 40.0;
  const PHI_FLOOR_DEG = 25.0;

  function makeLayer(o) {
    const L = Object.assign({
      name: "Layer", thickness: 1, gamma: 18, gammaSat: null,
      drainage: "drained", phi: 0, cohesion: 0, elasticModulus: null,
      sptN: null, energyRatio: 60, cc: null, cr: null, e0: null, ocr: 1,
      soilClass: "clean_sand_nc", notes: [],
    }, o);
    if (!(L.thickness > 0)) throw new Error(`Layer "${L.name}": thickness must be > 0.`);
    if (!(L.gamma > 0)) throw new Error(`Layer "${L.name}": unit weight must be > 0.`);
    if (L.gammaSat === null || L.gammaSat === undefined) L.gammaSat = L.gamma;
    if (L.gammaSat < L.gamma)
      throw new Error(`Layer "${L.name}": saturated unit weight cannot be less than the moist value.`);
    if (L.gammaSat <= GAMMA_WATER)
      throw new Error(`Layer "${L.name}": saturated unit weight must exceed that of water (${GAMMA_WATER} kN/m³).`);
    if (!(L.phi >= 0 && L.phi < 60)) throw new Error(`Layer "${L.name}": phi must satisfy 0 <= phi < 60.`);
    if (L.cohesion < 0) throw new Error(`Layer "${L.name}": cohesion must be >= 0.`);
    if (L.ocr < 1) throw new Error(`Layer "${L.name}": OCR must be >= 1.`);
    if (L.drainage === "undrained" && L.phi !== 0)
      throw new Error(`Layer "${L.name}": an undrained analysis requires phi = 0.`);
    if (L.drainage === "undrained" && !(L.cohesion > 0))
      throw new Error(`Layer "${L.name}": an undrained analysis requires su > 0.`);
    if (!(L.soilClass in ALPHA_E)) throw new Error(`Layer "${L.name}": unknown soil class.`);
    L.gammaBuoyant = L.gammaSat - GAMMA_WATER;
    L.isCohesive = L.drainage === "undrained";
    return L;
  }

  function makeProfile(layers, waterTableDepth) {
    if (!layers || !layers.length) throw new Error("A soil profile needs at least one layer.");
    const wt = (waterTableDepth === null || waterTableDepth === undefined) ? Infinity : waterTableDepth;
    if (wt < 0) throw new Error("Water table depth must be >= 0.");
    const tops = [];
    let z = 0;
    for (const l of layers) { tops.push(z); z += l.thickness; }
    const totalDepth = z;

    function layerAt(depth) {
      if (depth < 0) throw new Error("Depth must be >= 0.");
      for (let i = 0; i < layers.length; i++)
        if (depth < tops[i] + layers[i].thickness) return layers[i];
      return layers[layers.length - 1];
    }
    function stressAt(depth) {
      if (depth < 0) throw new Error("Depth must be >= 0.");
      let total = 0, cur = 0;
      for (let i = 0; i < layers.length; i++) {
        const layer = layers[i], top = tops[i], bottom = top + layer.thickness;
        const segBottom = Math.min(bottom, depth);
        if (segBottom <= cur) continue;
        const dryTop = cur, dryBottom = Math.min(segBottom, Math.max(wt, cur));
        if (dryBottom > dryTop) total += layer.gamma * (dryBottom - dryTop);
        const wetTop = Math.max(cur, Math.min(wt, segBottom));
        if (segBottom > wetTop) total += layer.gammaSat * (segBottom - wetTop);
        cur = segBottom;
        if (cur >= depth) break;
      }
      if (depth > cur) {
        const last = layers[layers.length - 1];
        const dryBottom = Math.min(depth, Math.max(wt, cur));
        if (dryBottom > cur) total += last.gamma * (dryBottom - cur);
        const wetTop = Math.max(cur, Math.min(wt, depth));
        if (depth > wetTop) total += last.gammaSat * (depth - wetTop);
      }
      const u = Number.isFinite(wt) ? GAMMA_WATER * Math.max(0, depth - wt) : 0;
      return { depth, total, pore: u, effective: total - u };
    }
    return {
      layers, tops, totalDepth, waterTableDepth: wt, layerAt, stressAt,
      effectiveStress: d => stressAt(d).effective,
      layerTop: i => tops[i],
      layerBottom: i => tops[i] + layers[i].thickness,
      extendsBelow: d => totalDepth >= d - 1e-9,
    };
  }

  const n60 = (nField, energyRatio = 60) => nField * (energyRatio / 60.0);
  const overburdenFactor = (sv, cap = 1.7) =>
    sv <= 0 ? cap : Math.min(cap, Math.sqrt(P_ATM_KPA / sv));

  function phiFromSpt(nField, sigmaVEff, energyRatio = 60, method = "kulhawy_mayne_1990") {
    const notes = [];
    let sv = sigmaVEff;
    if (sv < SIGMA_V_FLOOR_KPA) {
      // Atmospheres, not kPa: the correlation normalises on atmospheric
      // pressure, so this is its natural frame and is dimensionless - which
      // keeps the note correct on a page displaying ksf as well as kPa.
      notes.push(`evaluated at the correlation's low-stress floor of ` +
        `${(SIGMA_V_FLOOR_KPA / P_ATM_KPA).toFixed(2)} atm rather than the actual ` +
        `${(sv / P_ATM_KPA).toFixed(2)} atm of effective overburden, which is below ` +
        `the range it was regressed over`);
      sv = SIGMA_V_FLOOR_KPA;
    }
    const n_60 = n60(nField, energyRatio);
    let phi, cite;
    if (method === "hatanaka_uchida_1996") {
      phi = Math.sqrt(20.0 * n_60 * overburdenFactor(sv)) + 20.0;
      cite = "Hatanaka & Uchida (1996)";
    } else if (method === "wolff_1989") {
      const n1 = n_60 * overburdenFactor(sv);
      phi = 27.1 + 0.3 * n1 - 0.00054 * n1 * n1;
      cite = "Wolff (1989)";
    } else {
      const denom = 12.2 + 20.3 * (Math.max(sv, 1e-6) / P_ATM_KPA);
      phi = deg(Math.atan(Math.pow(Math.max(n_60, 1e-6) / denom, 0.34)));
      cite = "Kulhawy & Mayne (1990)";
    }
    const raw = phi;
    phi = Math.max(PHI_FLOOR_DEG, Math.min(PHI_CAP_DEG, phi));
    if (raw > PHI_CAP_DEG)
      notes.push(`correlation returned ${raw.toFixed(1)}° and has been capped at ${PHI_CAP_DEG}°; ` +
                 `verify with triaxial data before relying on a higher friction angle`);
    else if (raw < PHI_FLOOR_DEG)
      notes.push(`correlation returned ${raw.toFixed(1)}°, raised to the ${PHI_FLOOR_DEG}° floor`);
    if (notes.length) cite = `${cite} [${notes.join("; ")}]`;
    return { phi, cite };
  }

  function esFromSpt(nField, energyRatio = 60, soilClass = "clean_sand_nc") {
    const a = ALPHA_E[soilClass];
    if (a === undefined) throw new Error(`Unknown soil class ${soilClass}`);
    return a * n60(nField, energyRatio) * P_ATM_KPA;
  }

  // ---- stress -------------------------------------------------------------
  function newmarkCorner(m, n) {
    if (m < 0 || n < 0) throw new Error("m and n must be non-negative.");
    if (m === 0 || n === 0) return 0;
    const m2 = m * m, n2 = n * n, s = m2 + n2 + 1.0, root = Math.sqrt(s);
    const num = 2.0 * m * n * root;
    const first = (num / (s + m2 * n2)) * ((m2 + n2 + 2.0) / s);
    // atan2 supplies the correct branch when m^2 n^2 > m^2+n^2+1; plain atan
    // would silently lose the +pi and collapse wide, shallow areas.
    const angle = Math.atan2(num, s - m2 * n2);
    return (first + angle) / (4.0 * Math.PI);
  }
  function boussinesqCenter(q, b, l, z) {
    if (z <= 0) return q;
    if (b <= 0 || l <= 0) throw new Error("Loaded area dimensions must be positive.");
    return 4.0 * q * newmarkCorner((b / 2) / z, (l / 2) / z);
  }
  function influenceDepth(b, l, q, threshold = 0.10, zMaxRatio = 10.0) {
    let lo = 0, hi = zMaxRatio * Math.max(b, l);
    for (let i = 0; i < 80; i++) {
      const mid = 0.5 * (lo + hi);
      if (boussinesqCenter(q, b, l, mid) > threshold * q) lo = mid; else hi = mid;
    }
    return 0.5 * (lo + hi);
  }

  // ---- bearing ------------------------------------------------------------
  function bearingFactors(phiDeg, method = "vesic") {
    if (phiDeg < 0 || phiDeg >= 60) throw new Error(`phi = ${phiDeg}° outside [0, 60).`);
    if (phiDeg === 0) return { nc: N_C_PHI_ZERO, nq: 1.0, ngamma: 0.0, method };
    const phi = rad(phiDeg);
    const nq = Math.exp(Math.PI * Math.tan(phi)) * Math.pow(Math.tan(rad(45 + phiDeg / 2)), 2);
    const nc = (nq - 1.0) / Math.tan(phi);
    let ngamma;
    if (method === "hansen") ngamma = 1.5 * (nq - 1.0) * Math.tan(phi);
    else if (method === "meyerhof") ngamma = (nq - 1.0) * Math.tan(1.4 * phi);
    else ngamma = 2.0 * (nq + 1.0) * Math.tan(phi);
    return { nc, nq, ngamma, method };
  }

  function shapeFactors(bEff, lEff, phiDeg, nq, nc) {
    const r = bEff / lEff, phi = rad(phiDeg);
    return { sc: 1 + r * (nq / nc), sq: 1 + r * Math.tan(phi), sg: Math.max(0.6, 1 - 0.4 * r) };
  }

  function depthFactors(df, b, phiDeg) {
    if (b <= 0) throw new Error("Footing width must be positive.");
    const ratio = df / b;
    const k = ratio <= 1.0 ? ratio : Math.atan(ratio);   // radians beyond Df/B = 1
    const phi = rad(phiDeg);
    const dq = 1 + 2 * Math.tan(phi) * Math.pow(1 - Math.sin(phi), 2) * k;
    const dc = phiDeg === 0 ? 1 + 0.4 * k
      : dq - (1 - dq) / (bearingFactors(phiDeg).nc * Math.tan(phi));
    return { dc, dq, dg: 1.0, k };
  }

  function inclinationFactors(v, h, bEff, lEff, phiDeg, cohesion, nc, nq, thetaFromL = 90) {
    if (h <= 0) return { ic: 1, iq: 1, ig: 1, m: 0 };
    if (v <= 0) throw new Error("Vertical load must be > 0 to evaluate load inclination.");
    const r = bEff / lEff;
    const mB = (2 + r) / (1 + r), mL = (2 + 1 / r) / (1 + 1 / r), th = rad(thetaFromL);
    const m = mL * Math.cos(th) ** 2 + mB * Math.sin(th) ** 2;
    const area = bEff * lEff, phi = rad(phiDeg);
    if (phiDeg === 0) {
      if (cohesion <= 0) throw new Error("phi = 0 analysis requires cohesion > 0.");
      return { ic: Math.max(1 - (m * h) / (area * cohesion * nc), 0), iq: 1, ig: 1, m };
    }
    const base = 1 - h / (v + (area * cohesion) / Math.tan(phi));
    if (base <= 0)
      throw new Error(`Horizontal load ${h.toFixed(1)} kN exceeds the available shear resistance; ` +
                      `the footing slides before it bears.`);
    const iq = Math.pow(base, m), ig = Math.pow(base, m + 1);
    return { ic: Math.max(iq - (1 - iq) / (nq - 1), 0), iq, ig, m };
  }

  function effectiveGamma(profile, df, b, gammaMoist) {
    // The note is QUALITATIVE and carries no numbers: the UI owns formatting
    // and knows the user's units. Embedding kN/m³ here leaks internal SI onto a
    // page displaying ksf and pcf.
    const dw = profile.waterTableDepth;
    const sub = profile.layerAt(df + b / 2).gammaBuoyant;
    if (!Number.isFinite(dw) || dw >= df + b)
      return { gamma: gammaMoist, note: "Case III — water table below the failure zone; no reduction.", belowBase: null };
    if (dw <= df)
      return { gamma: sub, note: "Case I — water table at or above the base; fully buoyant.", belowBase: 0 };
    const g = sub + ((dw - df) / b) * (gammaMoist - sub);
    return { gamma: g, note: "Case II — water table within B below the base; linearly interpolated.", belowBase: dw - df };
  }

  function averagedProperties(profile, df, b, influenceDepthRatio = 1.5) {
    const zTop = df, zBot = df + influenceDepthRatio * b;
    const warnings = [], seen = [];
    let z = zTop;
    while (z < zBot - 1e-9) {
      const layer = profile.layerAt(z);
      let end = zBot;
      for (let i = 0; i < profile.layers.length; i++)
        if (profile.layers[i] === layer) { end = Math.min(zBot, profile.layerBottom(i)); break; }
      if (end <= z) end = zBot;
      seen.push({ t: end - z, layer });
      z = end;
    }
    const totalT = seen.reduce((a, s) => a + s.t, 0);
    if (totalT <= 0) {
      const l = profile.layerAt(df);
      return { phi: l.phi, cohesion: l.cohesion, gammaMoist: l.gamma, drainage: l.drainage, warnings };
    }
    const tanPhi = seen.reduce((a, s) => a + s.t * Math.tan(rad(s.layer.phi)), 0) / totalT;
    const cohesion = seen.reduce((a, s) => a + s.t * s.layer.cohesion, 0) / totalT;
    const gamma = seen.reduce((a, s) => a + s.t * s.layer.gamma, 0) / totalT;

    const drainages = new Set(seen.map(s => s.layer.drainage));
    let drainage;
    if (drainages.size > 1) {
      warnings.push("The bearing failure zone spans both drained and undrained layers. " +
        "Averaged properties are NOT a valid substitute for checking each condition separately — " +
        "run the drained and undrained cases as two analyses and take the lower capacity.");
      drainage = drainages.has("undrained") ? "undrained" : "drained";
    } else drainage = [...drainages][0];

    if (seen.length > 1) {
      const strength = l => l.cohesion + 50.0 * Math.tan(rad(l.phi));
      const vals = seen.map(s => strength(s.layer));
      const lo = Math.min(...vals), hi = Math.max(...vals);
      if (lo > 0 && hi / lo > 1.5) {
        const top = seen[0].layer;
        const weakest = seen.reduce((a, s) => strength(s.layer) < strength(a.layer) ? s : a).layer;
        const strongest = seen.reduce((a, s) => strength(s.layer) > strength(a.layer) ? s : a).layer;
        if (weakest !== top)
          warnings.push(`Strong layer (${top.name}) over weaker layer (${weakest.name}) within the ` +
            `failure zone. The averaged solution is UNCONSERVATIVE here; a punching-shear check ` +
            `(Meyerhof & Hanna 1978) is required.`);
        else if (strongest !== top)
          warnings.push(`Weak layer (${top.name}) over stronger layer (${strongest.name}) within the ` +
            `failure zone. Averaging is conservative but crude; consider founding on the deeper stratum.`);
      }
    }
    return {
      phi: drainage === "undrained" ? 0 : deg(Math.atan(tanPhi)),
      cohesion, gammaMoist: gamma, drainage, warnings,
    };
  }

  function slidingResistance(v, bEff, lEff, phi, cohesion, interfaceFactor = 0.67) {
    return v * Math.tan(rad(interfaceFactor * phi)) +
           Math.min(cohesion, interfaceFactor * cohesion) * bEff * lEff;
  }

  function ultimateBearingCapacity(o) {
    const { profile, b, l, df, v } = o;
    const h = o.h || 0, mB = o.mB || 0, mL = o.mL || 0;
    const fs = o.factorOfSafety === undefined ? 3.0 : o.factorOfSafety;
    const method = o.method || "vesic";
    const idr = o.influenceDepthRatio === undefined ? 1.5 : o.influenceDepthRatio;
    const thetaFromL = o.thetaFromL === undefined ? 90 : o.thetaFromL;

    if (b <= 0 || l <= 0) throw new Error("Footing dimensions must be positive.");
    if (df < 0) throw new Error("Founding depth must be >= 0.");
    if (v <= 0) throw new Error("Vertical load must be > 0.");
    if (fs <= 1.0) throw new Error("Factor of safety must exceed 1.0.");

    const warnings = [];
    const eB = Math.abs(mB) / v, eL = Math.abs(mL) / v;
    if (eB >= b / 2 || eL >= l / 2)
      throw new Error(`Eccentricity exceeds half the footing dimension ` +
        `(e_B/B = ${(eB / b).toFixed(3)}, e_L/L = ${(eL / l).toFixed(3)}). The footing overturns.`);
    if (eB > b / 6 + 1e-12 || eL > l / 6 + 1e-12)
      warnings.push(`Resultant falls outside the kern (e_B/B = ${(eB / b).toFixed(3)}, ` +
        `e_L/L = ${(eL / l).toFixed(3)} vs 1/6 = 0.167). Bearing pressure distribution is ` +
        `triangular with uplift at one edge; confirm the structural design accounts for partial contact.`);

    const bRaw = b - 2 * eB, lRaw = l - 2 * eL;
    const bEff = Math.min(bRaw, lRaw), lEff = Math.max(bRaw, lRaw);

    const props = averagedProperties(profile, df, b, idr);
    warnings.push(...props.warnings);
    const { phi, cohesion, drainage } = props;

    const stress = profile.stressAt(df);
    const surcharge = drainage === "undrained" ? stress.total : stress.effective;

    const f = bearingFactors(phi, method);
    const sh = shapeFactors(bEff, lEff, phi, f.nq, f.nc);
    const dp = depthFactors(df, b, phi);
    const inc = inclinationFactors(v, h, bEff, lEff, phi, cohesion, f.nc, f.nq, thetaFromL);
    const eg = effectiveGamma(profile, df, b, props.gammaMoist);

    const termC = cohesion * f.nc * sh.sc * dp.dc * inc.ic;
    const termQ = surcharge * f.nq * sh.sq * dp.dq * inc.iq;
    const termG = 0.5 * eg.gamma * bEff * f.ngamma * sh.sg * dp.dg * inc.ig;
    const qUlt = termC + termQ + termG;

    if (!profile.extendsBelow(df + idr * b))
      warnings.push(`Boring terminates at ${profile.totalDepth.toFixed(2)} m but the bearing failure ` +
        `zone extends to ${(df + idr * b).toFixed(2)} m. The bottom layer has been extrapolated — ` +
        `verify with a deeper boring.`);

    return {
      qUlt, qNetUlt: qUlt - surcharge, qAllow: qUlt / fs,
      factorOfSafety: fs, b, l, bEff, lEff, df, cohesion, phi,
      surchargeQ: surcharge, gammaE: eg.gamma, drainage, factors: f,
      ...sh, ...dp, ...inc, kDepth: dp.k, mIncl: inc.m,
      termCohesion: termC, termSurcharge: termQ, termSelfWeight: termG,
      gwNote: eg.note, gwBelowBase: eg.belowBase, warnings,
    };
  }

  // ---- settlement ---------------------------------------------------------
  function schmertmannGeometry(lOverB) {
    const t = Math.min(1.0, Math.log10(Math.max(lOverB, 1.0)));
    return { iz0: 0.1 + 0.1 * t, zp: 0.5 + 0.5 * t, zmax: 2.0 + 2.0 * t };
  }
  function strainInfluence(zOverB, iz0, zp, zmax, izp) {
    if (zOverB <= 0) return iz0;
    if (zOverB >= zmax) return 0;
    if (zOverB <= zp) return iz0 + (izp - iz0) * (zOverB / zp);
    return (izp * (zmax - zOverB)) / (zmax - zp);
  }

  function sublayerGrid(profile, df, zBottom, target, forced = []) {
    const bounds = new Set([df, zBottom]);
    for (const z of forced) if (z > df && z < zBottom) bounds.add(z);
    for (let i = 0; i < profile.layers.length; i++)
      for (const z of [profile.layerTop(i), profile.layerBottom(i)])
        if (z > df && z < zBottom) bounds.add(z);
    const ordered = [...bounds].sort((a, b) => a - b);   // numeric, not lexicographic
    const out = [];
    for (let i = 0; i < ordered.length - 1; i++) {
      const a = ordered[i], bnd = ordered[i + 1];
      const n = Math.max(1, Math.ceil((bnd - a) / target));
      const step = (bnd - a) / n;
      for (let k = 0; k < n; k++) out.push([a + k * step, a + (k + 1) * step]);
    }
    return out;
  }

  function settlement(o) {
    const { profile, b, l, df, qGross } = o;
    const timeYears = o.timeYears === undefined ? 50.0 : o.timeYears;
    const creep = o.creep === undefined ? true : o.creep;
    const poisson = o.poisson === undefined ? 0.3 : o.poisson;
    if (b <= 0 || l <= 0) throw new Error("Footing dimensions must be positive.");
    if (timeYears <= 0) throw new Error("Design life must be > 0 years.");

    const warnings = [];
    const sigmaV0 = profile.effectiveStress(df);
    const netQ = qGross - sigmaV0;
    if (netQ <= 0)
      return { total: 0, immediate: 0, consolidation: 0, c1: 1, c2: 1,
        netPressure: netQ, sigmaV0Base: sigmaV0, izp: 0, zpOverB: 0, zmaxOverB: 0, sublayers: [],
        warnings: ["Net bearing pressure is zero or negative (full compensation); settlement " +
                   "taken as zero. Check heave and rebound separately."] };

    const geo = schmertmannGeometry(l / b);
    const sigmaZp = profile.effectiveStress(df + geo.zp * b);
    const izp = 0.5 + 0.1 * Math.sqrt(netQ / Math.max(sigmaZp, 1e-6));
    const c1 = Math.max(0.5, 1 - 0.5 * (sigmaV0 / netQ));
    const c2 = creep ? 1 + 0.2 * Math.log10(timeYears / 0.1) : 1.0;

    const zBottom = Math.max(df + geo.zmax * b,
                             df + Math.max(influenceDepth(b, l, netQ, 0.10), 0.01));
    if (!profile.extendsBelow(zBottom))
      warnings.push(`Settlement summation extends to ${zBottom.toFixed(2)} m but the boring ends at ` +
        `${profile.totalDepth.toFixed(2)} m. The bottom layer has been extrapolated; settlement may ` +
        `be underestimated if softer material exists below.`);

    const grid = sublayerGrid(profile, df, zBottom, Math.max(b / 10, 0.05),
                              [df + geo.zp * b, df + geo.zmax * b]);
    let immediate = 0, consol = 0, schmertmannSum = 0;
    const subs = [];

    for (const [zTop, zBot] of grid) {
      const thickness = zBot - zTop, zMid = 0.5 * (zTop + zBot);
      const layer = profile.layerAt(zMid), dzBelow = zMid - df;
      if (layer.drainage === "drained") {
        if (dzBelow > geo.zmax * b) continue;
        const iz = strainInfluence(dzBelow / b, geo.iz0, geo.zp, geo.zmax, izp);
        let es = layer.elasticModulus;
        if (es === null || es === undefined) {
          if (layer.sptN === null || layer.sptN === undefined)
            throw new Error(`Layer "${layer.name}": settlement needs either an elastic modulus or an SPT N value.`);
          es = esFromSpt(layer.sptN, layer.energyRatio, layer.soilClass);
          warnings.push(`Layer "${layer.name}": Es correlated from N = ${layer.sptN} as ` +
            `${(es / P_ATM_KPA).toFixed(0)} × atmospheric pressure, assuming soil class ` +
            `"${layer.soilClass}" (Kulhawy & Mayne 1990). Scatter is roughly a factor of 2 ` +
            `— confirm with CPT or lab data.`);
          layer.elasticModulus = es;
        }
        if (es <= 0) throw new Error(`Layer "${layer.name}": elastic modulus must be > 0.`);
        schmertmannSum += (iz / es) * thickness;
        subs.push({ zTop, zBot, layerName: layer.name, method: "Schmertmann", iz, es,
                    deltaSigma: boussinesqCenter(netQ, b, l, dzBelow),
                    sigma0: profile.effectiveStress(zMid), settlement: 0 });
      } else {
        const sigma0 = profile.effectiveStress(zMid);
        const dsig = boussinesqCenter(netQ, b, l, dzBelow);
        if (dsig < 0.01 * netQ) continue;
        const sigmaP = layer.ocr * sigma0, sigmaF = sigma0 + dsig;
        if (!(layer.cc > 0 && layer.e0 > 0)) {
          warnings.push(`Layer "${layer.name}" is cohesive but has no Cc/e0; its consolidation ` +
            `settlement is NOT included. Supply Cc and e0 or the total settlement is unconservative.`);
          continue;
        }
        const cc = layer.cc, cr = (layer.cr === null || layer.cr === undefined) ? cc / 6 : layer.cr;
        let s = 0;
        if (sigmaF <= sigmaP) s = (thickness * cr / (1 + layer.e0)) * Math.log10(sigmaF / sigma0);
        else {
          if (sigmaP > sigma0) s += (thickness * cr / (1 + layer.e0)) * Math.log10(sigmaP / sigma0);
          s += (thickness * cc / (1 + layer.e0)) * Math.log10(sigmaF / Math.max(sigmaP, sigma0));
        }
        consol += s;
        let si = 0;
        if (layer.elasticModulus) { si = dsig * (1 - poisson ** 2) * thickness / layer.elasticModulus; immediate += si; }
        subs.push({ zTop, zBot, layerName: layer.name, method: "Consolidation", sigma0,
                    deltaSigma: dsig, sigmaP, es: layer.elasticModulus || 0, settlement: s + si });
      }
    }

    const sSchmertmann = c1 * c2 * netQ * schmertmannSum;
    for (const r of subs)
      if (r.method === "Schmertmann") r.settlement = c1 * c2 * netQ * (r.iz / r.es) * (r.zBot - r.zTop);
    immediate += sSchmertmann;

    return { total: immediate + consol, immediate, consolidation: consol, c1, c2,
      netPressure: netQ, sigmaV0Base: sigmaV0, izp, zpOverB: geo.zp, zmaxOverB: geo.zmax,
      sublayers: subs, warnings: [...new Set(warnings)] };
  }

  // ---- design codes -------------------------------------------------------
  const CODES = {
    us_asd: {
      key: "us_asd", name: "United States", subtitle: "Allowable Stress Design",
      approach: "ASD", factorOfSafety: 3.0, factorOfSafetySliding: 1.5,
      settlementLimit: 0.0254, combinations: [],
      citation: "IBC / ASCE 7 allowable stress design; factor of safety per customary practice",
      notes: [
        "FS = 3.0 on ultimate bearing capacity is customary US geotechnical practice for sustained (dead plus live) loading. It is NOT a value the IBC prescribes — IBC Chapter 18 gives presumptive load-bearing values rather than a factor of safety. The project geotechnical report governs.",
        "Where a load combination includes wind or seismic, US practice commonly permits a reduced factor of safety (or the equivalent one-third increase in allowable pressure). This tool does not apply that automatically — set the factor of safety deliberately for the case you are checking.",
        "Bearing capacity and settlement are both checked at SERVICE (unfactored) load. Do not enter factored loads.",
      ],
    },
    canada_lsd: {
      key: "canada_lsd", name: "Canada", subtitle: "Limit States Design",
      approach: "LSD", resistanceFactor: 0.5, resistanceFactorSliding: 0.8,
      settlementLimit: 0.025,
      combinations: [{ name: "1.4D", dead: 1.4, live: 0.0 },
                     { name: "1.25D + 1.5L", dead: 1.25, live: 1.5 }],
      counteracting: { name: "0.9D + 1.5L", dead: 0.9, live: 1.5 },
      citation: "NBC 2020 Part 4 limit states design; geotechnical resistance factors after the Canadian Foundation Engineering Manual",
      notes: [
        "Geotechnical resistance factor Φ = 0.5 for bearing resistance of shallow foundations at ULS, and 0.8 for sliding, follow the Canadian Foundation Engineering Manual. Confirm against the edition your jurisdiction adopts.",
        "Load combinations are NBC 2020 Table 4.1.3.2 reduced to the dead and live cases: 1.4D and 1.25D + 1.5L. A full design must also consider snow, wind and seismic combinations, which this tool does not form.",
        "Provinces amend the NBC. Ontario (OBC), British Columbia, Alberta and Quebec all publish their own editions; verify factors and combinations against the code actually in force for the site.",
        "Serviceability (settlement) is checked at UNFACTORED load. Only the ULS bearing check uses factored loads.",
      ],
    },
  };
  const factored = (combo, d, l) => combo.dead * d + combo.live * l;
  function governingCombination(code, d, l) {
    if (!code.combinations.length)
      throw new Error(`${code.name} is an ${code.approach} framework and has no ULS load combinations.`);
    let best = code.combinations[0];
    for (const c of code.combinations) if (factored(c, d, l) > factored(best, d, l)) best = c;
    return { combo: best, value: factored(best, d, l) };
  }

  // ---- design solver ------------------------------------------------------
  const estimateThickness = (b, columnB) =>
    Math.max(0.30, Math.ceil(((b - columnB) / 2 * 0.5) / 0.05) * 0.05);
  const grossPressure = (v, b, l, df, t, gammaSoil) =>
    v / (b * l) + t * GAMMA_CONCRETE + Math.max(0, df - t) * gammaSoil;

  function designFooting(profile, load, criteria) {
    const c = criteria, code = c.code;
    const df = load.embedment !== undefined && load.embedment !== null ? load.embedment : c.minEmbedment;
    if (df < c.minEmbedment)
      throw new Error(`${load.mark}: embedment is less than the required minimum.`);
    const v = load.dead + load.live;
    if (!(v > 0)) throw new Error(`${load.mark}: total service vertical load must be > 0.`);
    const props = averagedProperties(profile, df, c.minWidth, c.influenceDepthRatio);
    const gammaSoil = props.gammaMoist;

    function evaluate(b) {
      const l = b * c.aspectRatio, t = estimateThickness(b, load.columnB), area = b * l;
      const qService = grossPressure(v, b, l, df, t, gammaSoil);
      const selfWeight = t * GAMMA_CONCRETE + Math.max(0, df - t) * gammaSoil;

      let qDemand, comboLabel, deadFactor;
      if (code.approach === "ASD") {
        qDemand = qService; comboLabel = "service (D + L)"; deadFactor = 1.0;
      } else {
        const g = governingCombination(code, load.dead, load.live);
        qDemand = g.value / area + g.combo.dead * selfWeight;
        comboLabel = g.combo.name; deadFactor = g.combo.dead;
      }
      const vTotal = qDemand * area;
      const scale = code.approach === "LSD" ? deadFactor : 1.0;
      const mB = (load.momentB || 0) * scale, mL = (load.momentL || 0) * scale;
      const hUls = (load.horizontal || 0) * scale;

      let br;
      try {
        br = ultimateBearingCapacity({ profile, b, l, df, v: vTotal, h: hUls, mB, mL,
          factorOfSafety: c.factorOfSafetyBearing, method: c.bearingMethod,
          influenceDepthRatio: c.influenceDepthRatio });
      } catch (e) { return { design: null, reason: e.message }; }

      let capacity, factorLabel;
      if (code.approach === "ASD") {
        capacity = br.qAllow; factorLabel = `FS = ${c.factorOfSafetyBearing}`;
      } else {
        const phi = c.resistanceFactorBearing || code.resistanceFactor;
        capacity = phi * br.qUlt; factorLabel = `Φ = ${phi}`;
      }
      const lambda = qService > 0 ? qDemand / qService : 1.0;
      const uls = { approach: code.approach, demand: qDemand, capacity, combination: comboLabel,
        factorLabel, qUlt: br.qUlt, qService, loadFactorRatio: lambda,
        utilisation: capacity > 0 ? qDemand / capacity : Infinity,
        equivalentGlobalFs: capacity > 0 ? (br.qUlt * lambda) / capacity : Infinity,
        ok: qDemand <= capacity };

      const st = settlement({ profile, b, l, df, qGross: qService, timeYears: c.timeYears });
      const settleUtil = st.total / c.settlementLimit;
      const settleOk = st.total <= c.settlementLimit;

      let slidingFs = null, slidingOk = true;
      if (load.horizontal > 0) {
        if (code.approach === "LSD") {
          const cc = code.counteracting;
          const vResist = (factored(cc, load.dead, load.live) / area + cc.dead * selfWeight) * area;
          const phiSlide = code.resistanceFactorSliding || 0.8;
          slidingFs = (phiSlide * slidingResistance(vResist, br.bEff, br.lEff, br.phi, br.cohesion)) / hUls;
          slidingOk = slidingFs >= 1.0;
        } else {
          slidingFs = slidingResistance(vTotal, br.bEff, br.lEff, br.phi, br.cohesion) / load.horizontal;
          slidingOk = slidingFs >= c.factorOfSafetySliding;
        }
      }
      let overturningOk = true;
      if (mB || mL) {
        const mOvt = Math.abs(mB) + hUls * df;
        if (mOvt > 0) overturningOk = (vTotal * b / 2) / mOvt >= c.factorOfSafetyOverturning;
      }
      let governing = uls.utilisation >= settleUtil ? "Bearing capacity" : "Settlement";
      if (!slidingOk) governing = "Sliding"; else if (!overturningOk) governing = "Overturning";

      return { design: {
        mark: load.mark, ok: uls.ok && settleOk && slidingOk && overturningOk,
        b, l, df, thickness: t, governing, qApplied: qDemand, qAllow: capacity,
        qService, bearingUtilisation: uls.utilisation, totalSettlement: st.total,
        settlementUtilisation: settleUtil, slidingFs, concreteVolume: b * l * t,
        bearing: br, settlementResult: st, uls,
        warnings: [...br.warnings, ...st.warnings],
      }, reason: "" };
    }

    const nSteps = Math.floor((c.maxWidth - c.minWidth) / c.sizeIncrement) + 1;
    const trials = [];
    let firstOk = null, lastFail = "";
    for (let i = 0; i < nSteps; i++) {
      const b = c.minWidth + i * c.sizeIncrement;
      if (b > c.maxWidth + 1e-9) break;
      const { design, reason } = evaluate(b);
      if (!design) { lastFail = reason; continue; }
      trials.push(design);
      if (design.ok) { firstOk = design; break; }
    }
    if (firstOk === null)
      return { mark: load.mark, ok: false, df, governing: "NO SOLUTION", b: 0,
               message: diagnose(load, c, trials, lastFail, evaluate), warnings: [] };
    checkMonotonic(evaluate, c, firstOk);
    return firstOk;
  }

  function probeBeyond(evaluate, c, trials) {
    const r = { solutionB: null, bestB: 0, bestSettlement: Infinity, maxProbed: c.maxWidth };
    for (const d of trials)
      if (d.totalSettlement < r.bestSettlement) { r.bestSettlement = d.totalSettlement; r.bestB = d.b; }
    for (const factor of [1.25, 1.5, 2.0, 3.0]) {
      const b = c.maxWidth * factor;
      r.maxProbed = b;
      const { design } = evaluate(b);
      if (!design) continue;
      if (design.totalSettlement < r.bestSettlement) { r.bestSettlement = design.totalSettlement; r.bestB = b; }
      if (design.ok && r.solutionB === null) { r.solutionB = b; break; }
    }
    if (!Number.isFinite(r.bestSettlement)) r.bestSettlement = 0;
    return r;
  }

  function checkMonotonic(evaluate, c, result) {
    for (const step of [1, 2, 4, 8]) {
      const b = result.b + step * c.sizeIncrement;
      if (b > c.maxWidth) break;
      const { design } = evaluate(b);
      if (!design) continue;
      if (design.totalSettlement > c.settlementLimit) {
        result.warnings.push(`Non-monotonic settlement: enlarging the footing to B = ${b.toFixed(2)} m ` +
          `INCREASES settlement to ${(design.totalSettlement * 1000).toFixed(1)} mm, exceeding the ` +
          `${(c.settlementLimit * 1000).toFixed(0)} mm limit. A deeper compressible stratum is being ` +
          `stressed. Do not size this footing by inspection.`);
        break;
      }
    }
  }

  function diagnose(load, c, trials, lastFail, evaluate) {
    const u = c.units || units("SI");
    const ln = v => `${u.fromLength(v).toFixed(2)} ${u.labels.length}`;
    const st = v => `${u.fromSettle(v).toFixed(3)} ${u.labels.small}`;
    const head = `No footing between ${ln(c.minWidth)} and ${ln(c.maxWidth)} satisfies the criteria for ${load.mark}.`;
    if (!trials.length) return `${head} The solver could not evaluate any trial size. ${lastFail}`.trim();

    const worst = trials[trials.length - 1];
    const parts = [head,
      `At the largest size tried (B = ${ln(worst.b)}) bearing utilisation is ` +
      `${worst.bearingUtilisation.toFixed(2)} and settlement utilisation is ${worst.settlementUtilisation.toFixed(2)}.`];

    if (worst.settlementUtilisation > 1.0) {
      const sr = worst.settlementResult;
      const share = sr && sr.total > 0 ? sr.consolidation / sr.total : 0;
      if (share > 0.5) {
        const byLayer = {};
        for (const s of sr.sublayers)
          if (s.method === "Consolidation") byLayer[s.layerName] = (byLayer[s.layerName] || 0) + s.settlement;
        const culprit = Object.keys(byLayer).reduce((a, k) => byLayer[k] > (byLayer[a] || -1) ? k : a,
                                                    Object.keys(byLayer)[0] || "a cohesive stratum");
        parts.push(`Settlement governs: ${st(worst.totalSettlement)} against a limit of ` +
          `${st(c.settlementLimit)}, and ${(share * 100).toFixed(0)}% of it is consolidation in "${culprit}".`);
      } else {
        parts.push(`Settlement governs: ${st(worst.totalSettlement)} against a limit of ${st(c.settlementLimit)}.`);
      }
      const probe = probeBeyond(evaluate, c, trials);
      if (probe.solutionB !== null)
        parts.push(`Probing past the search range: a footing DOES work at B = ${ln(probe.solutionB)}. ` +
          `Raise the maximum width to at least that and re-run, then weigh the extra excavation and ` +
          `concrete against ground improvement.`);
      else
        parts.push(`Probing out to ${ln(probe.maxProbed)} found no working size. The least settlement at ` +
          `ANY width tried is ${st(probe.bestSettlement)} at B = ${ln(probe.bestB)}, still above the ` +
          `${st(c.settlementLimit)} limit. Widening cannot solve this: a wider footing pushes its stress ` +
          `bulb deeper into the compressible stratum, cancelling the lower contact pressure. The real ` +
          `options are ground improvement, a mat, or deep foundations — or confirming with the ` +
          `structural engineer whether ${st(probe.bestSettlement)} is tolerable.`);
    } else {
      parts.push("Bearing capacity governs. Founding deeper reaches stronger material and raises " +
        "capacity faster than widening does.");
    }
    if (lastFail) parts.push(`Solver note: ${lastFail}`);
    return parts.join(" ");
  }

  return { FT_TO_M, KIP_TO_KN, KSF_TO_KPA, PCF_TO_KNM3, P_ATM_KPA, GAMMA_WATER,
    GAMMA_CONCRETE, ALPHA_E, units, makeLayer, makeProfile, n60, overburdenFactor,
    phiFromSpt, esFromSpt, newmarkCorner, boussinesqCenter, influenceDepth,
    bearingFactors, shapeFactors, depthFactors, inclinationFactors, effectiveGamma,
    averagedProperties, slidingResistance, ultimateBearingCapacity,
    schmertmannGeometry, strainInfluence, settlement, CODES, governingCombination,
    estimateThickness, grossPressure, designFooting };
})();
if (typeof module !== "undefined" && module.exports) module.exports = Burh;
if (typeof globalThis !== "undefined") globalThis.Burh = Burh;
