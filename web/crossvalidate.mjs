/* Replay Python-generated cases through the browser engine and compare.
 *
 * The browser tool is only as trustworthy as its agreement with the validated
 * Python engine. Any divergence beyond TOL on a scalar, or ANY disagreement on
 * a discrete outcome (solved / governing criterion / load combination), fails.
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const Burh = require("./engine.js");

const TOL = 1e-9;
const cases = JSON.parse(readFileSync(new URL("./cases.json", import.meta.url), "utf8"));

const SCALARS = ["b", "q_ult", "q_demand", "q_capacity", "q_service", "settlement",
  "bearing_util", "settle_util", "phi", "nq", "ngamma", "surcharge", "gamma_e",
  "b_eff", "sliding_fs", "equiv_fs", "immediate", "consolidation"];

const JS_KEY = {
  b: d => d.b, q_ult: d => d.bearing.qUlt, q_demand: d => d.qApplied,
  q_capacity: d => d.qAllow, q_service: d => d.qService,
  settlement: d => d.totalSettlement, bearing_util: d => d.bearingUtilisation,
  settle_util: d => d.settlementUtilisation, phi: d => d.bearing.phi,
  nq: d => d.bearing.factors.nq, ngamma: d => d.bearing.factors.ngamma,
  surcharge: d => d.bearing.surchargeQ, gamma_e: d => d.bearing.gammaE,
  b_eff: d => d.bearing.bEff, sliding_fs: d => d.slidingFs,
  equiv_fs: d => d.uls.equivalentGlobalFs, immediate: d => d.settlementResult.immediate,
  consolidation: d => d.settlementResult.consolidation,
};

let checked = 0, failures = [], worst = { key: "", rel: 0, i: -1 };

cases.forEach((c, i) => {
  const layers = c.layers.map(l => Burh.makeLayer({
    name: l.name, thickness: l.thickness, gamma: l.gamma, gammaSat: l.gamma_sat,
    drainage: l.drainage, phi: l.phi, cohesion: l.cohesion,
    elasticModulus: l.elastic_modulus, cc: l.cc, cr: l.cr, e0: l.e0,
    ocr: l.ocr === undefined ? 1 : l.ocr,
    soilClass: l.soil_class || "clean_sand_nc",
  }));
  const profile = Burh.makeProfile(layers, c.water_table === null ? Infinity : c.water_table);
  const cr = c.criteria;
  const criteria = {
    code: Burh.CODES[cr.code],
    factorOfSafetyBearing: cr.factor_of_safety_bearing,
    resistanceFactorBearing: cr.resistance_factor_bearing,
    factorOfSafetySliding: 1.5, factorOfSafetyOverturning: 2.0,
    settlementLimit: cr.settlement_limit, minWidth: cr.min_width,
    maxWidth: cr.max_width, sizeIncrement: cr.size_increment,
    minEmbedment: cr.min_embedment, aspectRatio: cr.aspect_ratio,
    bearingMethod: cr.bearing_method, timeYears: cr.time_years,
    influenceDepthRatio: cr.influence_depth_ratio,
  };
  const ld = c.load;
  const load = { mark: ld.mark, dead: ld.dead, live: ld.live,
    horizontal: ld.horizontal, momentB: ld.moment_b, momentL: 0,
    columnB: ld.column_b, columnL: ld.column_l };

  const exp = c.expected;
  let got;
  try { got = Burh.designFooting(profile, load, criteria); }
  catch (e) {
    if (!exp.error) failures.push(`case ${i}: JS threw "${e.message}", Python did not`);
    return;
  }
  if (exp.error) { failures.push(`case ${i}: Python rejected, JS did not`); return; }

  if (!!got.ok !== !!exp.ok) {
    failures.push(`case ${i}: solved mismatch (py ${exp.ok}, js ${got.ok})`); return;
  }
  if (got.governing !== exp.governing)
    failures.push(`case ${i}: governing mismatch (py "${exp.governing}", js "${got.governing}")`);
  if (!exp.ok) return;                       // no-solution: nothing further to compare
  if (exp.combination && got.uls.combination !== exp.combination)
    failures.push(`case ${i}: load combination mismatch (py "${exp.combination}", js "${got.uls.combination}")`);

  for (const key of SCALARS) {
    const e = exp[key];
    if (e === null || e === undefined) continue;
    const g = JS_KEY[key](got);
    if (g === null || g === undefined) { failures.push(`case ${i}: ${key} missing in JS`); continue; }
    const rel = Math.abs(g - e) / Math.max(Math.abs(e), 1e-12);
    checked++;
    if (rel > worst.rel) worst = { key, rel, i };
    if (rel > TOL)
      failures.push(`case ${i}: ${key} py=${e} js=${g} rel=${rel.toExponential(3)}`);
  }
});

console.log(`cases:            ${cases.length}`);
console.log(`scalars compared: ${checked}`);
console.log(`worst deviation:  ${worst.rel.toExponential(3)} on "${worst.key}" (case ${worst.i})`);
console.log(`tolerance:        ${TOL.toExponential(0)}`);
if (failures.length) {
  console.log(`\nFAILURES (${failures.length}), first 12:`);
  failures.slice(0, 12).forEach(f => console.log("  " + f));
  process.exit(1);
}
console.log("\nPASS - the browser engine matches the Python engine on every case.");
