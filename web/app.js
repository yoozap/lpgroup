import * as THREE from 'three/webgpu';
import {
	pass, mrt, output, velocity, vec3, vec4, vec2, float, uniform, screenUV,
	normalViewGeometry,
	sample, normalView, packNormalToRGB, unpackRGBToNormal, builtinAOContext, mix,
	saturate, pow, length, Fn, fract, sin, dot, positionWorld, smoothstep,
	convertToTexture, texture, uv, oneMinus, positionWorldDirection,
	fog, equirectUV, normalize, cameraPosition, max, exp,
	normalWorld, reflect, cross, step as atLeast,
	attribute, positionLocal, screenCoordinate,
} from 'three/tsl';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { SunLight } from 'three/addons/lights/SunLight.js';
import { SunLightNode } from 'three/addons/lights/SunLightNode.js';
import { ao } from 'three/addons/tsl/display/GTAONode.js';
import { traa } from 'three/addons/tsl/display/TRAANode.js';
import { bloom } from 'three/addons/tsl/display/BloomNode.js';
import { chromaticAberration } from 'three/addons/tsl/display/ChromaticAberrationNode.js';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';
import { makeSky, skyEquirect, dither, SKY_LOOK } from './sky.js';
import { buildMaterials } from './materials.js';
/* The real building's floors - the plan frame, the level and flat lookup,
 * the interiors' weld and the floor view's drawing. See levels.js. */
import * as LVL from './levels.js';
import { createWalker, furnitureSolids, WALK as BW } from './walk.js';

/* ------------------------------------------------------------------ *
 * Camera solved from the reference photograph.
 *  f  = 1431 px at a 2048 px wide frame   (25.15 mm on a 36 mm sensor)
 *  principal point sits 1660 px down a 1920 px tall frame, so the lens
 *  is shifted up by 1660-960 px: a two point perspective, verticals stay
 *  vertical. The rise is baked straight into the projection matrix.
 * ------------------------------------------------------------------ */
const IMG_W = 2048, IMG_H = 1920, F_PX = 1431, PPY = 1660, EYE = 1.65;
const FRAME_AR = IMG_W / IMG_H;
const FOV_Y = 2 * Math.atan( IMG_H / ( 2 * F_PX ) ) * 180 / Math.PI;   // 67.71 deg
// principal point as a fraction down the frame -> the clip space rise that
// turns a level camera into a shift lens. Applied straight to the projection
// matrix so temporal jitter (TRAA) can still offset the frustum underneath it.
const LENS_RISE = 2 * ( PPY / IMG_H ) - 1;                             // 0.72917

const SUN_ELEV = 58.0, SUN_AZI = -30.6;    // degrees, matched to the reference
// Blender XY azimuth -> three.js: (x, y, z) = (cos.cos, sin(el), -cos.sin)
const se = SUN_ELEV * Math.PI / 180, sa = SUN_AZI * Math.PI / 180;
const SUN_DIR = new THREE.Vector3(
	Math.cos( se ) * Math.cos( sa ), Math.sin( se ), -Math.cos( se ) * Math.sin( sa ) ).normalize();
const SUN_COLOR = new THREE.Color( 1.0, 0.957, 0.886 );

/* Where the hero camera stands. The lab holds it exactly where the
 * photograph was taken. The page dollies it straight up the street - same
 * eye height, same lens, same direction, so the solved framing is
 * untouched and only the building grows in it. ?push=0 puts it back. */
const __q = new URLSearchParams( location.search );
const __embed = document.body.dataset.embed === '1';
const HERO_PUSH = __embed ? + ( __q.get( 'push' ) ?? 34 ) : 0;
/* ...and how much of the rise it keeps. The lab holds the solved 0.729,
 * which puts the horizon 86% down the frame - most of a 16:9 window is
 * then sky. The page keeps verticals vertical but lowers the rise, so the
 * building sits in the middle of its own frame instead of along the foot
 * of it. The hero is the only shot this touches. */
const HERO_SHIFT = __embed ? + ( __q.get( 'rise' ) ?? 0.34 ) : LENS_RISE;
/* ...and how far across. The hero's type is set bottom left, so the whole
 * shot is slid right by a horizontal shift of the same kind: the frustum
 * moves, the camera does not, so verticals stay vertical and the angles the
 * shots were flown at are untouched - the building simply lives in the
 * right of the frame, where the type is not. `?pan=0` centres it again. */
const HERO_PAN = __embed ? + ( __q.get( 'pan' ) ?? 0.16 ) : 0;

/* ------------------------------------------------------------------ embed
 * index.html - the landing page - hosts this same scene behind its hero
 * section: one renderer, the same solved shot, and none of the lab's chrome.
 * It sets `data-embed="1"` on <body>; everything guarded by EMBED below only
 * happens there, so lab.html and the golden shots taken from it are
 * untouched. Because the landing page carries no HUD, every control is
 * looked up through `$`, which answers for a missing element with a stub
 * that takes the same calls and does nothing.
 * ------------------------------------------------------------------ */
const EMBED = document.body.dataset.embed === '1';
const NULLEL = {
	checked: false, disabled: false, hidden: true, textContent: '', value: '',
	style: { setProperty() {}, getPropertyValue() { return ''; } },
	classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
	setAttribute() {}, removeAttribute() {}, addEventListener() {}, click() {}, focus() {},
};
const $ = ( id ) => document.getElementById( id ) || NULLEL;
/* The landing page listens rather than reaches in: the scene announces what
 * it is doing on window, and takes instructions through window.LP. */
const announce = ( what, detail ) => dispatchEvent( new CustomEvent( 'lp:' + what, { detail } ) );

const boot = $( 'boot' );
const bootmsg = $( 'bootmsg' );
const bootbar = $( 'bootbar' );
const booterr = $( 'booterr' );
const stage = $( 'stage' );
const frameEl = $( 'frame' );
const hud = $( 'hud' );
// Boot ledger: every phase the page announces is timestamped, so the headless
// rig (tools/perf-rig.cjs) can price the boot without guessing from the bar.
const __perf = window.__perf = { marks: [], mark( m ) { this.marks.push( [ m, Math.round( performance.now() ) ] );
	/* ...and kept, so the last boot can be read back from a tab nobody was
	 * measuring. A rig's numbers and a real browser's are not the same
	 * numbers - this page booted in 1.9 s headless and 4.2 s in a window
	 * with devtools attached - and the one that matters is the one on the
	 * machine the visitor is using. `localStorage['lp.boot']`. */
	try { localStorage.setItem( 'lp.boot', JSON.stringify( this.marks ) ); } catch ( e ) {}
} };
const step = ( p, m ) => { bootbar.style.width = p + '%'; if ( m ) { bootmsg.textContent = m; __perf.mark( m ); } };

let renderer, scene, camera, controls, pipeline, aoPass, traaNode, clock, fly;
let prePass, scenePass;
let mode = 'hero';
/* Scene 1 is the street shot of the whole building. Scene 2 opens the
 * corner flat on one storey: the pieces of the building that stand where it
 * is are hidden and the flat (`flat*` nodes in the GLB) shown. */
let sceneNo = 1;
/* ...and WHICH storey. Clicking a floor in the street shot opens that one;
 * the panel's Scene 2 button and the page's "start the tour" open the top,
 * which is the floor the build fitted the flat to and the one every number
 * in `scene_meta.json` is measured on. 0 until the meta is in. */
let sceneFloor = 0;
let meta = null;
/* The sales plan, rectified to a top-down metre image and laid on the flat's
 * own floor so the two can be checked against each other opening by opening.
 * `Mirror the plan` flips it along the facade, because our corner unit and
 * the unit in the render are opposite hands. */
let planOverlay = null;
let planMirror = true;
/* where the compare wipe sits, as a fraction of the photograph's band */
let splitT = 0.5;
/* Developer mode. With ?dev=1 the flat is left unbatched so every piece is
 * its own object, a gizmo is attached to whatever you click, and the panel
 * reports the piece's name and its position in the flat's own metres - the
 * same numbers lib_flat.py is written in, so a move here can be typed
 * straight back into the source. */
const DEV = new URLSearchParams( location.search ).has( 'dev' );
let gizmo = null, picked = null;
const moved = new Map();
const groups = { main: null, tower: null, cut: null, flat: null, leaf: null };
/* Going into the flat, the piece of building standing over it - roof,
 * parapet, the top-floor facade and gable, the mass - is sliced away by a
 * horizontal plane that sweeps down from the roof to the flat's floor, so
 * the building is cut open from the top. Coming back the plane sweeps up
 * and the building closes. Those `*__cut` nodes live in a ClippingGroup,
 * so nothing else feels the plane. The plane keeps y <= constant. */
const cutPlane = new THREE.Plane( new THREE.Vector3( 0, - 1, 0 ), 1e4 );
let cutTop = 0, cutBottom = 0;
/* The same cut, one storey at a time. `cutPlane` only reaches the pieces the
 * build pre-split for the top floor, so it can open the roof and nothing
 * else; a visitor who clicks the fifth storey wants the four floors standing
 * over it gone as well. That is the whole of block A against a second plane:
 * `groups.tower` holds every piece of the block - its mass, its facade and
 * gable, its windows and its loggias - and `groups.cut` hangs underneath it,
 * so the top-floor cells feel both planes and vanish with either. Nested
 * clipping groups union their planes, which is exactly the rule wanted here.
 *
 * It rests at 1e4 - above the city, clipping nothing - and the top floor
 * leaves it there: that storey already has its own pre-split cut and the
 * roof it keeps standing behind the flat is part of the shot. */
const towerPlane = new THREE.Plane( new THREE.Vector3( 0, - 1, 0 ), 1e4 );
let towerTop = 0;
/* Everything that moves between the scenes - the camera flight and the cut
 * - runs on these. A tween's clock starts on the first frame that draws it,
 * so a hitch or a background tab between the click and that frame never
 * skips part of the move. */
const tweens = [];
const easeInOut = ( t ) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow( - 2 * t + 2, 3 ) / 2;
const smoother = ( t ) => t * t * t * ( t * ( t * 6 - 15 ) + 10 );
const gradeAmount = uniform( 1.0 );
const aoStrength = uniform( 1.0 );
/* How much of the street's vignette a frame wears: all of it on the street,
 * less under a ceiling (see `bwLight`). 1 is the street's grade exactly. */
const vignAmount = uniform( 1.0 );

/* ------------------------------------------------------------------ idling
 * The shot stands still unless something moves it, so the page stops redrawing
 * the same frame sixty times a second: a render is owed only once something
 * changes the image, and because TRAA needs a few frames to resolve, every
 * change buys a short run of them. The canvas keeps the last frame while
 * nothing is owed, so a parked hero shot costs no GPU at all - and a drag or a
 * flight still runs at full rate, because moving the camera owes frames. */
const SETTLE = 20;
let owed = SETTLE;
const invalidate = ( n = SETTLE ) => { owed = Math.max( owed, n ); };
/* ------------------------------------------------------------ moving shot
 * The still frame is the one that gets held against the photograph, so it is
 * drawn at the full density the solved shot asks for. A moving one is not:
 * while the camera is in motion the two scene passes render at MOVE_SCALE of
 * the frame and the ambient occlusion at half of that again - which is where
 * nearly all of the frame's cost is, the scene being fill bound rather than
 * geometry bound - and everything returns to full as soon as the shot
 * settles, with frames in hand for the temporal AA to resolve it. Switching
 * is free: the targets reallocate without a measurable hitch. It is the whole
 * frame that is scaled, not the two passes on their own - scaling a pass
 * leaves the temporal AA holding a full size history of a smaller picture,
 * and the copy between them fails validation.
 * ?moveres=1 turns it off, ?moveres=0.5 pushes it further. */
const MOVE_SCALE = + ( new URLSearchParams( location.search ).get( 'moveres' ) || 0.7 );
const MOVE_HOLD = 6;                    // still frames before full comes back
let moveFrames = 0, fullRes = true, basePR = 0;

/* ------------------------------------------------------ adaptive density
 * The frame is fill bound almost exactly - measured on this machine it
 * costs 9.7 ms per million pixels shaded, whatever happens to be in them,
 * and halving the ambient occlusion's own resolution buys only 4 of its
 * 56 ms. So the one dial worth turning is how many pixels a MOVING frame
 * covers, and a dial fixed at 0.7 cannot be right on two machines: it
 * leaves a fast one soft and still misses on a slow one.
 *
 * The page turns it by the clock instead. While the shot moves it holds
 * the largest frame that still lands inside a display interval, steps
 * down the moment it misses several in a row, and probes back up only
 * after a long clean run - and a step it has already failed at is not
 * tried again for PROBE_AFTER, so it settles instead of breathing. The
 * moment the shot stands still it goes back to the full density and
 * spends its SETTLE frames resolving there, because a parked frame is
 * drawn a handful of times and then never again: quality there is free.
 *
 * The lab keeps the fixed dial, because `perf-shots/golden-s1.png` is
 * measured against its density. ?moveres= pins this one for an A/B.      */
const ADAPT = ( document.body.dataset.embed === '1' )
	&& ! new URLSearchParams( location.search ).has( 'moveres' );
/* The ladder stops at half of the solved density, which on a 2x display is
 * one buffer pixel per CSS pixel. Below that the hero stops being a
 * photograph of a building, and a machine that cannot hold 60 fps there is
 * better off dropping a frame than being shown mush. It starts partway
 * down rather than at the top, so the first seconds - which overlap the
 * background compiles - are never slower than the fixed dial used to be. */
const STEPS = [ 1, 0.90, 0.81, 0.73, 0.66, 0.60, 0.55, 0.50 ];
const STEP0 = 3;
/* The occlusion is resolved at the full frame when the shot is still -
 * that is the frame held against the photograph - and at half of it while
 * the shot moves, where the temporal AA has motion to hide it under. */
const AO_MOVE = + ( __q.get( 'aomove' ) ?? 0.5 );
function setAoScale( still ) {
	if ( aoPass ) aoPass.resolutionScale = still ? 1 : AO_MOVE;
}
const FRAME_CEIL = + ( new URLSearchParams( location.search ).get( 'ceil' ) ?? 18.5 );
/* The shadow map is drawn once and kept, so its resolution costs memory
 * and one frame of boot, not frame time. */
const SHADOW_PX = + ( new URLSearchParams( location.search ).get( 'shadow' ) || 4096 );
/* Aerial perspective: 1 - exp( -(d/AERIAL)^AERIAL_P ), scaled by AERIAL_AMT.
 * `?haze=0` turns it off for an A/B, `?haze=1.4` lays it on. */
const AERIAL = uniform( 1 / 780 );
const AERIAL_P = uniform( 1.55 );
const AERIAL_AMT = uniform(
	+ ( new URLSearchParams( location.search ).get( 'haze' ) ?? 1 ) );
/* `?ladder=old` puts ALL of this session's ladder changes back at once -
 * the opening window, the restored rung, the display-relative stall limit
 * and the quick first climb - so an A/B is one flag rather than four, and
 * cannot accidentally test three of them. */
const LADDER_OLD = __q.get( 'ladder' ) === 'old';
const PROBE_AFTER = 20000;              // ms before a failed step is retried
/* A frame over the stall limit is not evidence about density - it is a compile, a
 * texture upload or a hidden tab. 200 ms was chosen when a frame cost 56 ms
 * and it is far too generous now that one costs 13: at the rungs this page
 * runs at, dropping from the top of the ladder to the floor saves about
 * 14 ms, so a frame 95 ms over budget CANNOT be a density problem - no
 * density on the ladder would have fixed it - and reading it as one sent
 * the ladder straight to the floor over a single texture landing. The limit
 * is read off the display instead: four intervals, which keeps the genuine
 * 25-33 ms misses as evidence and throws out the stalls. `?stall=` pins it.
 *
 * MISSES is how many frames must miss the interval before the ladder moves:
 * enough that one slow frame is not a verdict, few enough that a visitor
 * does not watch it decide. */
const STALL_IV = + ( __q.get( 'stall' ) || 0 );
const stallMs = () => STALL_IV || ( LADDER_OLD ? 200 : Math.max( 80, ( frameIv || 16.7 ) * 4 ) );
const MISSES = 4;
let prStep = STEP0, prCap = 0, probeAt = 0, probeWait = PROBE_AFTER;
let overRun = 0, cleanRun = 0, holdFor = 0, lastDrawAt = 0, missWin = 0;
/* The display's own interval, learnt rather than assumed - about 16.7 ms
 * here, 8.3 on a 120 Hz panel - from the frames that FIT, which are the
 * ones pinned to it. The descent does NOT use it (see the dead end there);
 * `stallMs()` does, so that "this frame is a compile, not a density
 * verdict" is a judgement about the display rather than a number chosen
 * when a frame cost 56 ms. */
let frameIv = 0;
/* Has any rung ever been ruled out here? Until one has, the ladder is
 * still finding the machine's level and there is no reason to spend three
 * seconds a rung looking for it; afterwards it is probing a density it has
 * already failed at, and three seconds is right. `prCap` cannot answer
 * this on its own - 0 means both "no cap" and "capped at full density". */
let hadVerdict = false;
/* A frame drawn while the show flat is warming is a compile and a first
 * draw, not evidence about density - the same reason `STALL` exists, except
 * these land at 30-70 ms rather than over 200. Counted as evidence they were
 * a verdict: four of them in the first second sent the ladder straight to its
 * floor, `prCap` pinned it there, and `probeWait` doubled to 40 s - so the
 * hero spent the whole visit at half density. The warm raises this while it
 * runs and clears the ladder's memory when it is done. */
let warming = false;
/* ...and it covers the WHOLE opening, not just the warm: the frames right
 * after the veil lifts are first draws too - empty TRAA history, textures
 * landing, the first time each material is seen - and they were three rungs
 * of descent before the warm had even started. Ended by the warm, or by a
 * fallback for a page where the warm never runs. */
/* ...and the opening is not over when the WARM is over. Measured second by
 * second on a 40 s ride: the flat's warm finishes at 2.4 s, but frames do
 * not become honest until about 5 - textures are still landing, the temporal
 * AA has no history, and every surface the rail brings round the corner is
 * drawn for the first time. Ending the window on the warm meant three
 * descents in seconds 1 to 4, each one a VERDICT: `prCap` pinned to the
 * floor and `probeWait` doubled to a minute, so a machine that holds 2 Mpx
 * comfortably spent its whole visit at 1.44. The window now ends on
 * whichever is LATER, the warm or a floor on the clock.
 * ?warmfloor=0 ends it with the warm, for the A/B. */
const WARM_FLOOR = + ( __q.get( 'warmfloor' ) ?? ( LADDER_OLD ? 0 : 5000 ) );
let warmFloorAt = 0;
function endWarm() {
	if ( ! warming ) return;
	const left = warmFloorAt - performance.now();
	if ( left > 0 ) { setTimeout( endWarm, left + 16 ); return; }
	warming = false;
	/* Giving the RUNG back here - `prStep = STEP0`, on the argument that
	 * if the opening's frames are not evidence then they are not evidence
	 * about the rung either - was built and is OFF, because it measures
	 * worse and the reason is instructive.
	 *
	 * It is a blind jump, and it lands at the one moment the page is least
	 * able to hold it: the instant this window closes is the instant
	 * misses start counting as VERDICTS again, and the opening is still
	 * noisy either side of any fixed deadline. Measured: the restored rung
	 * missed within the second, the descent that followed set `prCap` to
	 * the floor and doubled `probeWait` to forty seconds, and the hero
	 * spent the rest of the ride at 1.44 Mpx - where simply climbing from
	 * where it stood reached 2.51 and held it.
	 *
	 * The slow recovery this was meant to fix is real; `TRY_FAST` is the
	 * answer to it. Climbing is evidence-led and self-correcting, and a
	 * jump is neither. `?warmrung=1` to try it again. */
	if ( WARM_RUNG && prStep > STEP0 ) prStep = STEP0;
	ladderReset();
	invalidate( 2 );
}
function ladderReset() {
	prCap = 0; probeAt = 0; probeWait = PROBE_AFTER; hadVerdict = false;
	overRun = 0; cleanRun = 0; missWin = 0; holdFor = 0; lastDrawAt = 0;
}

/* ------------------------------------------------------- the still frame
 * A parked frame is drawn a handful of times and then never again, so
 * quality there is free in a way that quality in a moving frame never is -
 * and the hero parks constantly: at both ends of the rail's sweep, the
 * moment a visitor stops dragging, and for as long as anyone actually
 * stops to look. So a still frame is not merely drawn at the solved
 * density, it is SUPERSAMPLED past it - rendered above the display's own
 * resolution and filtered down, which is real sampling rather than
 * sharpening, and which the temporal AA then accumulates over its SETTLE
 * frames. The cap keeps a weak GPU from being asked for a frame it would
 * take a second to draw.
 *
 * The lab keeps the plain solved density: `golden-s1.png` is measured at
 * it and a supersampled still would move every pixel. ?ss= tunes it.     */
/* ...but not the instant the shot stops. The rail holds for RAIL_PAUSE at
 * each end of its sweep, and supersampling those would buy nothing - the
 * eye has no time for it - while making the frame that RESUMES the sweep
 * four times the work, which is a visible hitch at the start of every
 * move. So a still frame earns its supersampling by standing still longer
 * than the rail ever holds: after a drag, where the camera parks for
 * RAIL_IDLE, it gets it. */
const SS = + ( new URLSearchParams( location.search ).get( 'ss' ) ?? 1.5 );
/* How much a still frame may cost, in ms. The old cap was a pixel count -
 * 11 Mpx, which on this machine is a 107 ms frame - and a frame that long
 * is felt even when nothing is moving: it is the latency of every pointer
 * move for as long as the burst lasts, which is what hovering the facade
 * after the shot parked felt like. The budget is in TIME now and the page
 * works out the pixels from what it has measured: `msPerMpx`, taken from
 * the same clean frames the density ladder reads. ?stillceil= tunes it. */
const STILL_CEIL = + ( new URLSearchParams( location.search ).get( 'stillceil' ) ?? 45 );
const SS_MAX_MPX = 11;                  // the fallback, before anything is measured
const SS_DWELL = 100;                   // still frames before it is spent

/* ------------------------------------------------ the flat gets the best
 * A flat is the only thing on this page anybody is buying, and it was
 * getting the page's WORST picture. Measured at 1512x710: the street runs
 * at 10 ms a megapixel and the floor view at 7.5, so both have room left
 * over and the still frame supersamples them - the floor view settles at
 * 2.38 effective pixel ratio. Step inside a flat and every pixel is the
 * full material path with glass, parquet and ambient occlusion in it,
 * 17 ms a megapixel open and 27 standing in a room - so the same budget
 * bought no supersample at all, the ladder cut the density to pay for the
 * shading, and the parquet came back in pixels. The shot a visitor is
 * there to study was the one shot drawn soft.
 *
 * So the flat is given its own budget, and a bigger one. It can be bigger
 * because of WHAT it is: a still frame is drawn ONCE, after two full
 * seconds of nobody touching anything (STILL_DWELL then SS_DWELL), and the
 * page is idle on either side of it. The visitor has stopped and is
 * reading the room. A frame that takes a fifth of a second to arrive and
 * then stands there sharp is exactly the right trade there, where it would
 * be the wrong one on a hero that never parks.
 *
 * A TIME ceiling alone cannot hold it. The budget divides by what a pixel
 * costs, and a pixel gets cheaper as the density rises - the fixed work in
 * a frame is spread over more of them - so the two chase each other
 * upward. Measured: at a 220 ms ceiling it settled on a pixel ratio of 4,
 * a 23 megapixel buffer and a 274 ms frame; dropping the ceiling to 160
 * only pushed the learnt cost per pixel down to match and it settled on
 * the same 23 Mpx. So the real stop is a count of PIXELS, which nothing
 * can argue with, and the time ceiling is the second of the two.
 *
 * Moving is untouched - the density ladder still owns every frame where
 * anything is in motion, which is the whole of `STEPS` below. This is the
 * parked frame and nothing else. */
const FLAT_CEIL = + ( new URLSearchParams( location.search ).get( 'flatceil' ) ?? 160 );
const FLAT_SS = + ( new URLSearchParams( location.search ).get( 'flatss' ) ?? 2 );
/* ...and the stop that holds: megapixels, whatever the clock says. 16 is
 * about 2.8 times a 1600x900 window's own pixels - a true 1.67x supersample
 * in each axis, against the 1.0 the flat was getting - and it lands the
 * parked frame near 100 ms rather than 270. */
const FLAT_MAX_MPX = + ( new URLSearchParams( location.search ).get( 'flatmpx' ) ?? 16 );
/* Deep in scene 2: one flat open, or standing in a room inside it. Not the
 * floor view - that is a drawing, it is cheap, and it already gets all the
 * density its own budget can buy. */
const inFlat = () => sceneNo === 2 && scene2View === 'plan' && planFocus >= 0;

/* What a megapixel costs - kept TWICE, because the two states do not cost
 * the same thing and one number averaged across both is wrong in the flat
 * either way. The street and the floor view run at 7 to 10 ms a megapixel;
 * a flat runs at 17 to 27. One EMA walking between them budgets the flat
 * out of the street's price the moment a visitor dives in, and the street
 * out of the flat's when they come back - each wrong for as many frames as
 * the blend takes to turn over. Two numbers, each learnt where it is
 * spent, and neither ever sees the other's frames. */
let stillFrames = 0, msPerMpx = 0, msPerMpxFlat = 0;
const pxCost = () => inFlat() ? msPerMpxFlat : msPerMpx;
const stillScale = () => {
	const deep = inFlat();
	const cap = deep ? FLAT_SS : SS;
	if ( ! ADAPT || cap <= 1 || stillFrames < SS_DWELL ) return 1;
	const px = innerWidth * innerHeight * basePR * basePR / 1e6;
	const ceil = deep ? FLAT_CEIL : STILL_CEIL;
	const cost = pxCost();
	const room = cost > 0 ? ceil / cost : SS_MAX_MPX;
	const budget = deep ? Math.min( FLAT_MAX_MPX, room ) : room;
	return Math.max( 1, Math.min( cap, Math.sqrt( budget / Math.max( 0.01, px ) ) ) );
};

/* The opening frames are not a parked shot. Nothing has moved yet, so
 * `moveFrames` is zero and the page would hand the full density - and on
 * the sales page the still frame's supersampling - to a hero nobody has
 * looked at yet, at 40 ms a frame, while the ladder sat with no evidence
 * to calibrate from (`rate()` ignores still frames). So the first frames
 * count as moving: they are drawn at the ladder's density, they feed it,
 * and the moment it knows what a pixel costs here the still rule takes
 * over and a genuinely parked shot gets its full density back. */
let calibrating = ADAPT, calibFrames = 0;
const stillNow = () => moveFrames === 0 && ! calibrating;
/* A shot that has only just stopped is not a shot anybody is studying: the
 * rail holds at each end, a visitor pauses between drags, and the opening
 * seconds stand still before the sweep begins. Going to the full density
 * for every one of those costs a 40 ms frame each time and buys a picture
 * nobody has time to look at - so the full density waits half a second of
 * stillness, and the supersample waits SS_DWELL beyond that. */
const STILL_DWELL = 30;
/* STILL_HOLD: a parked page must go quiet. The supersample is sized from
 * `msPerMpx`, and `rate()` re-learns that from the very still frames the
 * supersample draws; each re-learnt number moved the size by a percent or
 * two, `applyScale` resized, owed SETTLE more frames, and those re-learnt
 * it again - ~22 frames a second for ever on a parked hero or a floor view.
 * So within one still spell the chosen scale only moves when the new
 * answer differs by more than SS_BAND, at most SS_MOVES times, and is then
 * held until something moves (or the window, the pixel ratio or the
 * flat/street budget changes). Learning goes on; it is used next spell.
 * ?stillhold=old restores the old free-running scale exactly. */
const STILL_HOLD_OLD = __q.get( 'stillhold' ) === 'old';
const SS_BAND = 0.04, SS_MOVES = 3;
let ssHeld = 0, ssMoves = 0, ssKey = '';
const stillPick = () => {
	const s = stillScale();
	if ( STILL_HOLD_OLD ) return s;
	const key = innerWidth + 'x' + innerHeight + '@' + basePR + ( inFlat() ? 'f' : 's' );
	if ( stillFrames < SS_DWELL ) { ssHeld = 0; return s; }    // not spent yet: 1
	if ( key !== ssKey || ! ssHeld ) { ssKey = key; ssHeld = s; ssMoves = 0; return s; }
	if ( ssMoves < SS_MOVES && Math.abs( s - ssHeld ) > SS_BAND * ssHeld ) { ssHeld = s; ssMoves ++; }
	return ssHeld;
};
const currentPR = () => basePR * ( ADAPT
	? ( stillNow() && stillFrames >= STILL_DWELL ? stillPick() : STEPS[ prStep ] )
	: ( fullRes ? 1 : MOVE_SCALE ) );

/* resize the drawing buffer to whatever density is wanted now */
function applyScale() {
	const pr = currentPR();
	if ( ! basePR || ! renderer || Math.abs( pr - renderer.getPixelRatio() ) < 1e-3 ) return;
	renderer.setPixelRatio( pr );
	renderer.setSize( innerWidth, innerHeight, false );
	renderer.domElement.style.width = innerWidth + 'px';
	renderer.domElement.style.height = innerHeight + 'px';
	setAoScale( stillNow() );
	if ( stillNow() ) invalidate( SETTLE );      // frames for the full-size resolve
}

/* -------------------------------------------- what a frame really costs
 * It cannot be read off the interval between frames, and it cannot be
 * measured either. At 60 Hz a frame that fits is handed back at 16.7 ms
 * whether it took 4 ms or 16, and about one flip in twelve is missed for
 * reasons of the display's own and comes back at 33 - so `dt` reports the
 * DISPLAY, not the work, and a page with half its frame to spare looks
 * exactly like a page with none.
 *
 * Draining the queue after a frame and timing that was tried and thrown
 * away (`?probelog=1` on the commit before this one): the drain's promise
 * is resolved on the main thread, which is parked waiting for the next
 * rAF, so it timed the SCHEDULER - 85 to 91 ms for a frame the rigs
 * measure at 17. Per-pass GPU timestamps do not work on Metal/Dawn either
 * (see README). There is no honest number here.
 *
 * So the ladder climbs by TRYING instead. Every TRY_MS it takes a rung,
 * and the descent rule - which is evidence, not prediction - either keeps
 * it or sends it back and pins `prCap` there for a doubling interval. The
 * only cost of a failed try is half a second at a density that stutters,
 * and it self-damps: one failure at a rung buys twenty seconds of not
 * asking again, then forty. */
const TRY_MS = + ( __q.get( 'tryms' ) || 3000 );
/* ...and until the first verdict, much faster than that. From the floor
 * to the top of this ladder is seven rungs; at TRY_MS that is twenty-one
 * seconds of a first impression spent climbing, and the only thing a
 * visitor gets for the wait is the certainty that each rung held for three
 * whole seconds before the next was tried. A rung that does not hold costs
 * a handful of stuttering frames and the descent aims straight at the one
 * that does, so the search is cheap and it should be quick. */
const TRY_FAST = + ( __q.get( 'tryfast' ) || 700 );
const WARM_RUNG = ! LADDER_OLD && __q.get( 'warmrung' ) === '1';
let nextTry = 0;

/* one drawn frame's worth of evidence */
function rate() {
	const now = performance.now();
	const dt = lastDrawAt ? now - lastDrawAt : 0;
	lastDrawAt = now;
	if ( ! dt || dt > stallMs() ) return;        // first frame, a stall, a hidden tab
	/* What a million pixels cost here - the number the still frame spends
	 * its supersampling budget against. It is taken from STILL frames only,
	 * and only from ones that ran over the display's own interval, because
	 * those are the only frames whose duration is honest: a moving frame
	 * that fits is handed back at 16.7 ms whether it cost 4 ms or 16, so
	 * averaging those said ~11.6 ms/Mpx on a frame costing 8.3 and the
	 * parked hero was budgeted softer than the machine could draw it. A
	 * still frame at full density is well over the interval, so its own
	 * clock is the truth - and it is also exactly the frame being
	 * predicted, AO at full resolution and all. */
	const mpx = innerWidth * innerHeight * renderer.getPixelRatio() ** 2 / 1e6;
	if ( stillNow() ) {
		if ( mpx > 0.05 && dt > 18 ) {
			const m = dt / mpx;
			// ...into whichever of the two this frame was drawn for
			if ( inFlat() ) msPerMpxFlat = msPerMpxFlat ? msPerMpxFlat * 0.8 + m * 0.2 : m;
			else msPerMpx = msPerMpx ? msPerMpx * 0.8 + m * 0.2 : m;
		}
		overRun = cleanRun = 0; return;
	}
	if ( ! msPerMpx && mpx > 0.05 ) msPerMpx = dt / mpx;   // something to start from
	/* The flat has no number of its own until it has been stood still in
	 * once. Starting it from the street's would budget it four times too
	 * generously for the one frame that matters most, so it starts from a
	 * guess on the pessimistic side and the first still frame corrects it. */
	if ( ! msPerMpxFlat && msPerMpx ) msPerMpxFlat = msPerMpx * 3;
	if ( calibrating && ++ calibFrames >= 24 ) { calibrating = false; invalidate( SETTLE ); }
	if ( holdFor > 0 ) { holdFor --; return; }
	/* Misses are counted over a WINDOW, not in a row. A page that owes two
	 * frames and can draw one alternates fast, slow, fast, slow - which
	 * resets a consecutive counter on every other frame, so the ladder sat
	 * at a density that missed half of its frames and never moved. Half the
	 * window missing is a miss. */
	missWin = ( missWin << 1 | ( dt > FRAME_CEIL ? 1 : 0 ) ) & 0xfff;
	let missed = 0;
	for ( let w = missWin; w; w >>= 1 ) missed += w & 1;
	/* A frame that fits IS one display interval, so these are the clock. */
	if ( dt <= FRAME_CEIL ) frameIv = frameIv ? frameIv * 0.9 + dt * 0.1 : dt;
	if ( dt > FRAME_CEIL ) {
		cleanRun = 0;
		/* How FAR down, not just down. The frame is fill bound, so its cost
		 * goes with the pixel count and the pixel count with the square of
		 * the scale: a frame at 2.4x the interval wants about 1/1.55 of the
		 * density, which is four rungs of this ladder, not one. Stepping
		 * one rung per ten misses took eight seconds to find the density a
		 * machine could hold - eight seconds of the opening shot at 15 to
		 * 30 fps, which is the whole of what "it lags" was. Aiming straight
		 * at the rung the measurement asks for gets there in about one. */
		if ( ( ++ overRun >= MISSES || missed >= 6 ) && prStep < STEPS.length - 1 ) {
			/* DEAD END, measured 2026-10-20 - do not retry it.
			 *
			 * The argument was: `dt` is the display and the display is
			 * quantised, so a frame that misses one flip comes back at two
			 * intervals whether it cost 16.8 ms or 33, and dividing by it
			 * treats every single miss as a frame at 1.8x budget. A frame
			 * arriving at (k+1) intervals cost somewhere in ( k, k+1 ] of
			 * them, so `dt - iv` is its lower bound and the interval is
			 * what to divide by. It was built, and it made the hero DRIFT
			 * DOWN - 3.07 Mpx to 2.51 to 2.07 over ten seconds - where the
			 * line below holds 3.07 flat for the whole ride.
			 *
			 * The premise is simply false here. Pull every per-second
			 * median over the ceiling out of the rides in `tools/` and
			 * they come back 18.6, 19.1, 22.3, 24.6, 40.2, 54.8 - a
			 * continuous spread, and NOT ONE of thirty-four within 2.5 ms
			 * of a clean 33.3. The page is not hard-locked to the flip;
			 * `dt` is an honest cost, and `dt - iv` therefore understates
			 * it badly - a 22 ms frame reads as 5.3 ms of overrun and asks
			 * for one rung where it wants two.
			 *
			 * It also lands the ladder ON the cliff rather than below it.
			 * Dropping to exactly the rung that fits leaves the page
			 * missing a few frames a second at the edge, which the ladder
			 * then reads as more evidence, and it walks itself down. The
			 * overshoot the line below produces is the margin. */
			const want = STEPS[ prStep ] * Math.sqrt( FRAME_CEIL / dt );
			let aim = prStep + 1;
			while ( aim < STEPS.length - 1 && STEPS[ aim ] > want ) aim ++;
			/* ...but a miss during the OPENING is not a verdict on the
			 * density. The frames after the veil lifts are first draws -
			 * empty TRAA history, textures landing, every material seen for
			 * the first time - and the show flat's warm is compiles. Letting
			 * them set `prCap` and double `probeWait` is what left the hero
			 * at half density for the whole visit: three rungs lost in the
			 * first second, then locked out of climbing back for forty. So
			 * the ladder still FALLS while warming - those misses are real
			 * and a visitor sees them - but it does not conclude anything,
			 * and `endWarm` gives it a clean slate to climb from. */
			if ( ! warming ) {
				prCap = aim;                     // this density does not fit here
				hadVerdict = true;               // ...so stop hunting, start probing
				probeWait = Math.min( probeWait * 2, 60000 );
				probeAt = now + probeWait;
			}
			prStep = aim; overRun = 0; missWin = 0; holdFor = 24;
		}
	} else {
		overRun = 0;
		const mayRise = prStep > prCap || now > probeAt;
		/* Sixty frames in a row with none of them over the ceiling is a
		 * condition vsync jitter alone can stop from ever being met: at
		 * 1.44 Mpx this page misses about one frame in ten on timing noise
		 * alone, so an unbroken run of sixty has a chance of 0.2% - and the
		 * ladder sat on whatever rung the opening transient left it on for
		 * the whole visit. The try is on a clock now, and asks only that the
		 * recent window be nearly clean. */
		cleanRun ++;
		if ( now > nextTry && missed <= 2 && cleanRun >= 20 && prStep > 0 && mayRise ) {
			prStep --; cleanRun = 0; holdFor = 12;
			nextTry = now + ( hadVerdict || LADDER_OLD ? TRY_MS : TRY_FAST );
			if ( prStep < prCap ) prCap = prStep;
			invalidate( 2 );
		}
	}
}
/* The sun never moves and neither does the city, so the shadow map is drawn
 * once and kept. Everything that changes what casts - the cut sweeping down, a
 * scene switch, a piece dragged in developer mode - asks for a fresh one. */
let sun = null;
let hemi = null;                 // the sky's fill - and, walking, the room's: see `bwLight`
const shadowDirty = () => { if ( sun ) sun.shadow.needsUpdate = true; };
/* Scene 2's maps and pipelines, fetched and compiled once the street is up. */
let maps = null, scene2Ready = null, planTex = null;
/* The show flat arrives in its own file, after the street and behind the
 * first frame - see `loadFlat`. These are what that second parse needs and
 * cannot build for itself: the shaded materials `buildMaterials` made, and
 * the loader with its Draco decoder, which therefore cannot be disposed
 * when the street is done with it. */
let sceneMaterials = null, glbLoader = null, glbDraco = null, flatReady = null;
/* Is the flat's GEOMETRY in the scene? Not "has it been asked for" - the
 * difference is the whole of the bug the split shipped. Everything that can
 * put the flat on screen goes through `withFlat`, so there is one place to
 * be wrong rather than three. With the split off this is true from the
 * start and `withFlat` is a straight call. */
let flatIn = false;
/* The real-plan rebuild (blender/plans/CONTRACT.md): the building is the
 * architect's now, and the invented show flat - scene-flat.glb, the storey
 * hover, scene 2, the floor view, the rooms and the walk, all of which were
 * built on that one flat - is not built any more. Until the next stage puts
 * them back on the real interiors (web/interior/*.glb, web/plan_meta.json)
 * every way into them is shut HERE, quietly: `withFlat` does nothing,
 * `loadFlat`/`prepareScene2` fetch and warm nothing, the hover never arms,
 * and `setScene( 2 )` is refused. The street, the rail, the lab's orbit and
 * fly modes are untouched. */
const FLAT_GONE = true;
const withFlat = ( fn ) => {
	if ( FLAT_GONE ) return;
	if ( flatIn ) return fn();
	loadFlat().then( fn, fn );        // a flat that fails still opens, empty
};
/* ON, since the two holes below were closed - `?glbsplit=0` for the old
 * single file.
 *
 * It was off for one commit after it broke production.
 *
 * Splitting the model is right - it takes the first frame from 9.31 MB to
 * 5.71 - but it changes something the rest of the page assumed: the flat's
 * GEOMETRY used to be in the scene from boot, and became a download. There
 * is now a window, as long as that download takes, in which `groups.flat`
 * is empty - measured at 4 Mbps, it still held 0 meshes twenty seconds in -
 * and the hover arms on a 2.5 s deadline regardless, so the wall parted on
 * a storey with nothing in it.
 *
 * Two holes, both now closed through `withFlat`: the hover's arming
 * deadline starts when the flat is IN rather than when the pointer
 * arrives, and the storey CLICK - which does not have to come through a
 * hover at all - is gated the same way. Verified by looking at the frames
 * during the download window on a throttled link, which is the check that
 * was missing the first time: the timings were measured and the pictures
 * were not. */
const GLB_SPLIT = __q.get( 'glbsplit' ) !== '0';

init().catch( ( e ) => {
	console.error( e );
	bootmsg.textContent = 'could not start';
	booterr.innerHTML = ( navigator.gpu ? '' :
		'This page renders with <b>WebGPU</b>. Use Chrome&nbsp;113+, Edge, or Safari&nbsp;18+ with WebGPU enabled.<br><br>' )
		+ '<code style="font-size:11px;opacity:.75">' + String( e && e.message || e ) + '</code>';
} );

async function init() {

	if ( ! navigator.gpu ) throw new Error( 'navigator.gpu is unavailable' );

	step( 6, 'starting webgpu' );
	/* `?ts=1` asks the backend for WebGPU timestamp queries, which is the only
	 * way to see what a pass costs on the GPU rather than what the wall clock
	 * says the page took. It changes nothing about the render and is off by
	 * default: a query pool per frame is not free. tools/gputime.cjs reads it. */
	const TRACK_TS = new URLSearchParams( location.search ).get( 'ts' ) === '1';
	renderer = new THREE.WebGPURenderer( { antialias: false, alpha: false,
		trackTimestamp: TRACK_TS } );
	/* MEASUREMENT ONLY: ?nolight=1 turns the renderer's scene lighting off, so
	 * every material's shader is built without its lighting chain. The picture
	 * is wrong - that is not the point - it prices what the lighting costs in
	 * WGSL GENERATION, which is what the boot and the hover's wait are made
	 * of. See the pre-pass note in the README. */
	if ( __q.get( 'nolight' ) === '1' ) renderer.lighting.enabled = false;
	// render at the reference's own 2048 px width whatever the window size, so
	// a 3 px window pane survives instead of blurring into the wall
	renderer.setPixelRatio( Math.min( devicePixelRatio, 2 ) );
	renderer.toneMapping = THREE.AgXToneMapping;
	renderer.toneMappingExposure = 0.97;
	renderer.shadowMap.enabled = true;
	renderer.shadowMap.type = THREE.PCFSoftShadowMap;
	renderer.library.addLight( SunLightNode, SunLight );
	frameEl.insertBefore( renderer.domElement, frameEl.firstChild );
	await renderer.init();

	scene = new THREE.Scene();
	clock = new THREE.Clock();

	camera = new THREE.PerspectiveCamera( FOV_Y, FRAME_AR, 0.25, 2600 );
	installLensShift( camera );
	camera.lensPan = HERO_PAN;
	camera.position.set( 0, EYE, 0 );
	camera.lookAt( 0, EYE, -1 );
	camera.updateProjectionMatrix();

	// ------------------------------------------------------------- sky + ibl
	// One sky, used twice. What you look at is the analytic function itself,
	// evaluated per screen pixel, so the cirrus is as sharp as the frame and
	// the gradient cannot band. What lights the scene is the same function
	// rendered once into an equirectangular target - minus the sun disc, which
	// the SunLight below already accounts for.
	step( 16, 'building sky' );
	const skyLook = makeSky( { sunDir: SUN_DIR, disc: true, ...SKY_LOOK } );
	const skyLight = makeSky( { sunDir: SUN_DIR, disc: false } );
	/* The sky is the most expensive pixel on the page after the building
	 * itself: Perez, two domain-warped fbm decks of cirrus, a cumulus band,
	 * the disc and the haze, measured at 4.8 ms/Mpx - 27 to 30% of the
	 * frame - and three draws the background across the WHOLE frame, before
	 * the geometry covers it up, in both passes. It is also perfectly
	 * static: nothing in sky.js takes a time. So it is baked once, at boot,
	 * into an equirectangular target and sampled by direction - the same
	 * function, the same inputs, one evaluation per texel instead of one
	 * per pixel per frame. The dither stays on the sampled colour, because a
	 * 16-bit texture of a smooth gradient bands exactly where the analytic
	 * one did. Measured against the live model it is inside the capture
	 * noise, and pointed into the sun it is max 1/255.
	 * ?bg=live evaluates it per pixel again, ?bg=flat prices it, ?bgpx= sets
	 * the bake. 4096x2048 half-float is 67 MB of VRAM and 2048 measured the
	 * same, so a small device gets the small one. */
	const BG_MODE = __q.get( 'bg' ) || 'tex';
	const smallDevice = ( navigator.deviceMemory && navigator.deviceMemory <= 4 )
		|| Math.min( innerWidth, innerHeight ) < 700;
	const BG_PX = + ( __q.get( 'bgpx' ) || ( smallDevice ? 2048 : 4096 ) );
	let bgRT = null;
	if ( BG_MODE === 'flat' ) scene.backgroundNode = vec3( 0.42, 0.52, 0.68 );
	else if ( BG_MODE === 'live' ) scene.backgroundNode = dither( skyLook( positionWorldDirection ) );
	else {
		bgRT = skyEquirect( THREE, renderer, skyLook, BG_PX, BG_PX / 2 );
		scene.backgroundNode = dither(
			texture( bgRT.texture, equirectUV( positionWorldDirection ) ).rgb );
	}
	scene.backgroundIntensity = 1.0;
	const skyRT = skyEquirect( THREE, renderer, skyLight, 1024, 512 );
	const pmrem = new THREE.PMREMGenerator( renderer );
	scene.environment = pmrem.fromEquirectangular( skyRT.texture ).texture;
	scene.environmentIntensity = 1.45;
	const skyTex = skyRT.texture;

	// ----------------------------------------------- aerial perspective
	/* Distance is not free in a photograph. Three hundred metres of city
	 * air lifts a facade toward the colour of the sky behind it and takes
	 * most of its contrast with it; without that, every block in the frame
	 * carries the same weight and the city reads as a model on a table.
	 *
	 * The haze colour is the sky's own radiance along the view ray - the
	 * LOOK sky, which is what actually sits behind the buildings, so a far
	 * roofline dissolves into the gradient it is drawn against instead of
	 * fading to a flat grey. It is baked once into its own small equirect
	 * (no sun disc: a facade must not pick up a second sun) so a fragment
	 * pays one texture fetch rather than the whole analytic sky.
	 *
	 * Rays that point down sample the horizon rather than the sky's ground
	 * term: the air over the avenue is the same air, and the ground colour
	 * in the model exists only to keep the PMREM honest. */
	const hazeRT = skyEquirect( THREE, renderer,
		makeSky( { sunDir: SUN_DIR, disc: false, ...SKY_LOOK } ), 256, 128 );
	{
		const toEye = positionWorld.sub( cameraPosition );
		const dist = length( toEye );
		const hazeDir = normalize( vec3( toEye.x, max( toEye.y, float( 0.0 ) ), toEye.z ) );
		const hazeCol = texture( hazeRT.texture, equirectUV( hazeDir ) ).rgb;
		/* 1 - exp( -(d/D)^p ). p above 1 keeps the first hundred metres
		 * nearly clear - the building has to stay crisp - and then lets the
		 * far side of the avenue go, which is the curve a long lens sees. */
		const f = exp( pow( dist.mul( AERIAL ), AERIAL_P ).negate() ).oneMinus();
		scene.fogNode = fog( hazeCol, f.mul( AERIAL_AMT ) );
	}

	// ------------------------------------------------------------- sun
	sun = new SunLight( SUN_COLOR, 5.4 );
	sun.position.copy( SUN_DIR ).multiplyScalar( 400 );
	sun.castShadow = true;
	/* The map is drawn ONCE and then kept for the life of the page, so its
	 * size is paid for a single time - and it has to cover a 420 m frustum,
	 * where 2048 put roughly one texel on every 20 cm and the balcony
	 * soffits and window reveals came back as stairs. Quality here is
	 * nearly free in a way that per-frame quality never is. */
	sun.shadow.mapSize.set( SHADOW_PX, SHADOW_PX );
	if ( sun.shadow.camera ) { sun.shadow.camera.near = 1; sun.shadow.camera.far = SHADOW_FAR; }
	sun.shadow.bias = -0.00022;
	sun.shadow.normalBias = 0.04;
	// drawn on demand, not every frame: see shadowDirty()
	sun.shadow.autoUpdate = false;
	sun.shadow.needsUpdate = true;
	scene.add( sun );
	hemi = new THREE.HemisphereLight( 0x9ab4d8, 0x56503f, 0.22 );
	scene.add( hemi );

	// ------------------------------------------------------------- model
	step( 30, 'loading geometry' );
	const draco = new DRACOLoader().setDecoderPath(
		'./vendor/three/examples/jsm/libs/draco/' );
	/* The decoder is a separate download from a separate host, and without
	 * this it is not asked for until the model has landed and the first
	 * compressed mesh needs it - a round trip in the middle of the boot
	 * where nothing else is happening. */
	draco.preload();
	const loader = new GLTFLoader().setDRACOLoader( draco );
	// the show flat is a second file through the same loader - see `loadFlat`
	glbDraco = draco; glbLoader = loader;
	// the street's maps and the meta travel beside the model, not after it
	maps = makeMaps();
	const streetMaps = loadMapSet( false );
	const metaReq = fetch( './scene_meta.json' ).then( r => r.ok ? r.json() : null ).catch( () => null );
	/* The HTML put the model on the wire before the modules arrived (see the
	 * head of index.html); here it is only unwrapped. Anything wrong with
	 * it - no such global, a failed fetch - falls back to loading it the
	 * ordinary way, so the page cannot be broken by the optimisation. */
	const pre = window.__glb;
	let buf = null;
	if ( pre ) {
		const tick = setInterval( () => {
			const o = pre.progress;
			if ( o && o.total ) step( 30 + 30 * Math.min( 1, o.loaded / o.total ) );
		}, 60 );
		try { buf = await pre; } catch ( e ) {
			console.warn( 'the head\'s scene.glb fetch failed, loading it again:', e );
		}
		clearInterval( tick );
	}
	const gltf = buf
		? await new Promise( ( res, rej ) => loader.parse( buf, './', res, rej ) )
		: await loader.loadAsync( GLB_SPLIT ? './scene-street.glb' : './scene.glb', ( e ) => {
			if ( e.total ) step( 30 + 30 * e.loaded / e.total );
		} );
	/* Let the 10.6 MB go: the head's fetch resolved to an ArrayBuffer and
	 * `window.__glb` is a global, so without this the whole model stays in
	 * the heap for the life of the page, on top of everything three built
	 * from it. */
	buf = null;
	window.__glb = null;
	/* `draco.dispose()` used to be here. It cannot be: the show flat is a
	 * second Draco file through the same loader, and disposing the decoder
	 * takes its worker pool and its wasm module with it. `loadFlat` does it
	 * once the flat is in. */

	step( 64, 'shading surfaces' );
	meta = await metaReq;
	adoptPlan( meta );               // the plan the build measured, not our copy
	// plan metres <-> world, for everything the real building's levels do
	frameP = LVL.makeFrame( meta );
	await streetMaps;
	// the sky goes in with the scanned maps: the glazing samples it for the
	// light coming in through a window, with the same projection the
	// background and the PMREM use, so every reflection in the frame agrees
	maps.sky = skyTex;
	const { materials, XRAY } = buildMaterials( THREE, { sunDir: SUN_DIR, sunColor: SUN_COLOR, maps,
		flat: meta && meta.flat } );
	xray = XRAY;
	sceneMaterials = materials;          // ...and the flat, when it lands
	// the furniture keeps its own glTF materials, so it is the only thing
	// here whose textures nobody had set up: do that before they are used
	console.info( 'textures sharpened to anisotropy ' + maxAniso() + ':',
		sharpenTextures( gltf.scene ) );
	applyMaterials( gltf.scene, materials );
	scene.add( gltf.scene );

	step( 76, 'batching draw calls' );
	optimise( gltf.scene );
	// what the floor view needs to draw the storey as a plan: the row's own
	// bay table, and the patch on the materials that were just welded
	planSetupFrame();
	planSetupMaterials();
	buildPlanOverlay();

	// ------------------------------------------------------------- post
	step( 88, 'compiling shaders' );
	buildPipeline();

	// OrbitControls re-aims the camera in its constructor, so give it the hero
	// target first and restore the exact shot afterwards.
	controls = new OrbitControls( camera, renderer.domElement );
	controls.target.copy( siteCenter() );
	controls.enableDamping = true;
	controls.dampingFactor = 0.08;
	controls.enabled = false;
	controls.maxPolarAngle = Math.PI * 0.52;
	controls.minDistance = 2;
	controls.maxDistance = 900;
	controls.zoomSpeed = 1.1;
	fly = EMBED
		? makeFlyControls( camera, renderer.domElement, {
			wheel: false,                       // the wheel belongs to the page
			allow: () => flyAllowed,
			/* The floor view takes the drag off them - a pointer dragged
			 * across a plan slides the storey along - but INSIDE a room
			 * it is theirs again, because there a drag is a visitor
			 * turning on the spot. */
			drag: () => ! planDragOwns() || roomFocus >= 0,
			freeLook: () => bwOn,
			walk: walkStep,
			speed: 11,
			bounds: () => sceneNo === 2
				? { at: orbitTarget(), reach: 26, top: orbitTarget().y + 14 }
				: { at: siteCenter(), reach: 190, top: 130 },
		} )
		// the lab keeps flying as a mode, but a flat walked into is walked
		// in there too - see `setMode`
		: makeFlyControls( camera, renderer.domElement, { walk: walkStep, freeLook: () => bwOn } );
	resetShot();
	bwTouchWire( renderer.domElement );

	wireUI();
	if ( EMBED ) initEmbed();
	resize();
	addEventListener( 'resize', resize );
	// coming back to the tab: the canvas may have been dropped while it was
	// hidden, and nothing else would ask for the frame that redraws it
	addEventListener( 'visibilitychange', () => { if ( ! document.hidden ) invalidate(); } );
	addEventListener( 'focus', () => invalidate( 4 ) );

	// Scene 1 only. The show flat stays hidden, so none of it is compiled yet
	// and the street is on screen as soon as the street is ready.
	setScene( 1, false );
	await warmUp();
	if ( DEV ) initDev();
	step( 100, 'ready' );
	boot.classList.add( 'gone' );
	hud.hidden = false;
	renderer.setAnimationLoop( frame );
	/* Nothing the opening costs is evidence about how dense this machine can
	 * hold the hero - see `warming`. Cleared when the show flat's warm ends,
	 * or on a fallback for a page that never warms it. */
	warming = true;
	warmFloorAt = performance.now() + WARM_FLOOR;
	// the 4 s fallback is for a page whose flat never warms at all, and it
	// stays that long so `?warmfloor=0` reproduces the old behaviour exactly
	setTimeout( endWarm, Math.max( 4000, WARM_FLOOR ) + 16 );
	if ( FLAT_GONE ) {
		// the lab has no page around it, but the rigs drive it the same way
		if ( ! EMBED ) lvInstallApi( window.LP = window.LP || { invalidate } );
		/* The plan's own data is small and nothing waits for it - fetched
		 * behind the first frame so the first hover can name its flats. */
		setTimeout( () => { LVL.planMeta().then( ( pm ) => { lvPM = pm; }, () => {} );
			LVL.roomsLite().then( ( r ) => { lvLite = r; } ); }, 1200 );
		/* `#flat-37` opens flat 37 in the scene as well as on the page;
		 * `#walk-C1` and `#flat-37/walk` walk in (see `bwHash`). */
		const hs = decodeURIComponent( location.hash || '' );
		const m = /^#flat-([^/]+)$/.exec( hs );
		if ( /^#walk-|\/walk$/.test( hs ) ) setTimeout( bwHash, 400 );
		else if ( m ) setTimeout( () => lvOpenFlat( m[ 1 ] ), 400 );
	}
	announce( 'ready' );
	loadHood();
	// Everything Scene 2 needs - the show flat's maps and its pipelines - is
	// fetched and compiled in the background once the street is up.
	/* The flat used to be wanted only if somebody clicked, so the page put
	 * its warm off for twenty seconds and let the hero have the GPU. The
	 * hover changed that: the flat is now what a visitor sees a second in,
	 * through the open storey, and an uncompiled pipeline draws NOTHING -
	 * which is exactly what "items inside don't show sometimes" was. So it
	 * warms early here too, and the batches no longer wait for an idle that
	 * a sweeping hero never gives them. */
	/* The flat's pipelines are ~3 s of compiles, and a compile holds the
	 * frame loop off, so WHEN they are paid for used to be the difference
	 * between a clean opening shot and six seconds of hitching: the page
	 * waited for the visitor to show up - the first pointer over the canvas,
	 * the first wheel, the first key - or a long deadline for the visitor
	 * who only watches.
	 *
	 * That was the right trade while a batch cost 130 ms. It is not any
	 * more: the warm is paced by a time budget (WARM_MS) and its hitches are
	 * the size of a frame, while the price of waiting was the whole of what
	 * the user felt as "after refresh i need too much time to hover" - the
	 * warm cannot start when the pointer arrives AND be finished when it
	 * arrives. So it starts a breath after the page appears, and the intent
	 * listeners only bring that breath forward. */
	/* The levels' turn at the same breath: every storey shares its materials
	 * with every other, walls and furniture both, so one storey built behind
	 * the street is the pipelines of all of them. Without it the first floor
	 * a visitor opens stands unfurnished under the pointer for the 4-5 s its
	 * furniture takes to compile. */
	/* ...but on the sales page NOT at boot any more (owner, 2026-11-25:
	 * "too much loading - lazy-load, don't load the insides until I go to a
	 * storey"). Every visitor used to download a storey, the cores and its
	 * furniture (~1.3 MB on the wire, ~3 s of compile) within 80 ms of the
	 * first frame, whether they ever went in or not. Now it starts on INTENT:
	 * the pointer on a storey band (`lvSetHot`) or on a street door
	 * (`bwHotSet`) - typically a second or two before the click - and any
	 * storey opened by other means loads on demand (`lvPart`). The furniture
	 * warm is one piece per shader now, so the wait it can leave is short.
	 * `?prewarm=boot` restores the old behaviour for an A/B. */
	if ( FLAT_GONE ) {
		if ( ! EMBED ) setTimeout( lvPrewarm, 1200 );
		else if ( PREWARM_BOOT ) {
			const go = () => lvPrewarm();
			const once = { once: true, passive: true };
			renderer.domElement.addEventListener( 'pointermove', go, once );
			addEventListener( 'wheel', go, once );
			addEventListener( 'scroll', go, once );
			addEventListener( 'keydown', go, once );
			setTimeout( go, WARM2_AFTER );
		} else {
			/* ...but not as late as the band either (owner, 2026-11-26: "click
			 * on floor not works, animation not happened"). Waiting for the
			 * pointer to reach a storey left a quick click 1-2 s of nothing -
			 * and on a cold visit the street's own compiles hold the same
			 * gate for seconds more. A pointer moving over the picture is
			 * intent enough; a visitor who never touches it still loads
			 * nothing. */
			renderer.domElement.addEventListener( 'pointermove', () => lvPrewarm(), { once: true, passive: true } );
		}
	}
	if ( WARM2 && ! FLAT_GONE ) {
		/* The flat's 24 maps are a download, not a compile - they cost the
		 * GPU nothing and they are the first thing the warm awaits - so they
		 * are on the wire from here, before anything asks for them. */
		if ( maps ) loadMapSet( true );
		if ( ! EMBED ) setTimeout( prepareScene2, 1200 );
		else {
			const go = () => prepareScene2();
			const once = { once: true, passive: true };
			renderer.domElement.addEventListener( 'pointermove', go, once );
			addEventListener( 'wheel', go, once );
			addEventListener( 'scroll', go, once );
			addEventListener( 'keydown', go, once );
			setTimeout( go, WARM2_AFTER );
		}
	}

}

/* ------------------------------------------------------------- warm-up
 * Which pipeline a frame needs depends on the target it draws into, and this
 * page draws the scene twice: once into the prepass' normal and velocity
 * targets, once into the beauty target. `renderer.compileAsync( scene )`
 * warms neither - it compiles for the output state - which is why the old
 * boot still built most of its pipelines inside the first frames. A pass
 * knows its own target and MRT, so warming goes through the passes instead.
 * The passes only learn their formats when the graph is set up, which is the
 * first render, so one frame is drawn behind the veil first.
 * ?warm=none | old | pass (default) switches this for measurement. */
const WARM = new URLSearchParams( location.search ).get( 'warm' ) || 'first';
/* A compile borrows the renderer: it parks its own render context, target and
 * MRT on it and puts them back when it finishes. Anything that draws while it
 * is in flight - another compile, or a frame from the animation loop - draws
 * through that borrowed state, and the page dies with "Color target has no
 * corresponding fragment stage output" the moment the output quad is built
 * against a pass' two attachments. So compiles never overlap each other and
 * never overlap a frame: `compiling` holds the loop off, and every compile
 * here is awaited one at a time. */
let compiling = false;
let compileSince = 0;            // when the loop was last lent out (frame), 0 when it is not
/* A held frame shorter than this passes for a hitch; longer, a walk's HUD
 * shows its waiting mark rather than leaving a frozen picture unexplained. */
const BW_HOLD_CUE = 300;
const WARM2 = new URLSearchParams( location.search ).get( 'warm2' ) !== '0';
/* ...and how long the page waits for a visitor to touch something before it
 * warms the flat anyway. ?warm2after= in ms. */
const WARM2_AFTER = + ( new URLSearchParams( location.search ).get( 'warm2after' ) ?? 80 );
/* WHERE the show flat's pipelines are built. The obvious idea is 'boot':
 * behind the veil, in the warm frame that is already being drawn, so the
 * hover answers from the first frame a visitor sees and the second it costs
 * is spent against a boot bar instead of against a dead hover. It was built
 * and MEASURED, interleaved, and it is worse at both ends:
 *
 *   warm2in     page appears    hover works
 *   boot            3.6 s           3.9 s
 *   after           1.9 s           3.3 s
 *
 * The work is not the same second in both places. Carried in the street's
 * own warm frame the flat costs about 1.3 s rather than the 1.0 it costs in
 * its own frames afterwards, and - worse - the boot AWAITS the GPU after that
 * frame, so Dawn compiling the flat's 90 pipelines lands on the critical path
 * instead of happening on its own threads while the hero sweeps. A frame of
 * its own after the veil cannot be had either: a pass is
 * `NodeUpdateType.FRAME` and the frame id only advances in the renderer's
 * animation loop, which is not running yet. So 'after' stands, and 'boot' is
 * kept as the knob that shows why. */
const WARM2_IN = __q.get( 'warm2in' ) || 'after';
let flatWarmedInBoot = false;

async function warmUp() {
	const t0 = performance.now();
	if ( WARM === 'old' ) {
		groups.cut.visible = groups.flat.visible = true;
		await Promise.race( [ renderer.compileAsync( scene, camera ),
			new Promise( r => setTimeout( r, 7000 ) ) ] );
		setScene( 1, false );
	}
	if ( WARM === 'async' ) {
		// An empty frame first: it costs nothing to draw and it is what makes
		// the passes work out their formats, which they only do when the graph
		// is set up. With that known, both passes can be compiled through the
		// driver's async path - several pipelines at a time on its own threads
		// - instead of one at a time inside the first real frame.
		const vis = Object.values( groups ).map( g => g && g.visible );
		for ( const g of Object.values( groups ) ) if ( g ) g.visible = false;
		pipeline.render();
		Object.keys( groups ).forEach( ( k, i ) => { if ( groups[ k ] ) groups[ k ].visible = vis[ i ]; } );
		const job = ( async () => {
			compiling = true;
			try {
				await prePass.compileAsync( renderer );
				await scenePass.compileAsync( renderer );
			} finally { compiling = false; }
		} )();
		await Promise.race( [ job, new Promise( r => setTimeout( r, 12000 ) ) ] );
		pipeline.render();
		__perf.mark( 'first frame' );
	}
	if ( WARM !== 'none' && WARM !== 'async' ) {
		// One frame behind the veil. It draws the street into both passes, so
		// everything the shot needs is built here, in the states it is drawn
		// in - which is what `renderer.compileAsync( scene )` on its own never
		// did, because it warms the output state instead.
		const tWarm = performance.now();
		/* This takes about a second, and it is three.js turning every visible
		 * material's node graph into WGSL on the main thread - not Dawn
		 * compiling it, which is the ~210 ms drain below, and not the shadow
		 * map, whose 420 m frustum submits far more than the camera sees but
		 * which measured out at nothing (?shadowwarm=0 prices it). Drawing it
		 * in chunks so the bar could move was tried and is much worse: every
		 * chunk is another full frame, and one run of it took 22 seconds.
		 *
		 * What CAN be done about a blocked main thread is to let the bar
		 * glide on the compositor, which keeps animating while JavaScript
		 * stands still - otherwise it stops at 88% for the longest part of
		 * the boot, which is most of what a long load feels like. */
		bootbar.style.transition = 'width 1.8s cubic-bezier(.2,.7,.3,1)';
		bootbar.style.width = PIPES ? '93%' : '99%';   // the rest is `pipesSettled`'s
		const sw = __q.get( 'shadowwarm' ) !== '0';
		if ( ! sw && sun ) sun.shadow.needsUpdate = false;
		/* ...and the show flat rides in that same frame, on the page.
		 *
		 * The hover cannot part a wall until the flat behind it can be
		 * DRAWN - an unbuilt pipeline draws nothing at all in WebGPU - and
		 * building it is the same kind of second as the one above: 45
		 * materials' worth of node graph turned into WGSL, twice, once per
		 * pass. That second has to be spent somewhere. Spent after the veil
		 * lifts it is a second of a page that looks alive and whose hover is
		 * dead, which is what the user feels; spent here it is a second of a
		 * boot bar that is already gliding, and the hover answers from the
		 * first frame anybody sees.
		 *
		 * It has to be THIS frame and not a second render after it: a pass is
		 * `NodeUpdateType.FRAME`, so it runs its scene once per frame id, and
		 * the frame id only advances in the renderer's own animation loop -
		 * which has not been started yet behind the veil. A second
		 * `pipeline.render()` here redraws the output quad and nothing else:
		 * measured, it added one draw call and one triangle.
		 *
		 * The flat is carried to a storey first, or it is culled where it
		 * stands and nothing is warmed at all, and it casts no shadow while
		 * it is there: the shadow map is drawn ONCE and frozen, and a flat
		 * baked into it would sit in it for the whole visit.
		 * ?warm2in=after puts this back after the veil, for an A/B. */
		const unwarm = ( WARM2 && WARM2_IN === 'boot' && groups.flat
			&& meta && meta.block && meta.block.floors ) ? ( () => {
			const wasY = groups.flat.position.y, cast = [];
			groups.flat.traverse( ( o ) => {
				if ( o.isMesh ) { cast.push( o.castShadow ); o.castShadow = false; } } );
			groups.flat.position.y = ( 3 - meta.block.floors.n ) * meta.block.floors.h;
			groups.flat.visible = true;
			return () => {
				groups.flat.visible = false;
				groups.flat.position.y = wasY;
				let k = 0;
				groups.flat.traverse( ( o ) => { if ( o.isMesh ) o.castShadow = cast[ k ++ ]; } );
				flatWarmedInBoot = true;
			};
		} )() : null;
		const unglass = warmFloorGlass();
		const unband = lvWarmBands();          // ...and the storey bands' pipeline
		/* ...and the pipelines that frame needs are built SIDE BY SIDE first.
		 * See `pipesGather`: this is the difference between a first visit of
		 * thirty seconds and one of a few. The first `render()` draws nothing
		 * and asks for everything; the second, once they have all landed, is
		 * the warm frame proper. */
		let tAsked = 0, tBuilt = 0;
		if ( PIPES ) {
			pipesGather();
			pipeline.render();
			tAsked = performance.now();
			/* The main thread is free while they build, so for once the bar
			 * can say something true: it is handed back from the glide and
			 * walks 93 -> 99% with the pipelines that have actually landed.
			 * On a visit the OS has seen before that is a few frames; on a
			 * first one it is most of the boot, and a bar that moves with
			 * the work is the difference between a load and a hang. */
			bootbar.style.transition = 'width .25s linear';
			await pipesSettled( ( done, all ) => {
				bootbar.style.width = ( 93 + 6 * done / all ).toFixed( 1 ) + '%'; } );
			tBuilt = performance.now();
			/* A pass runs its scene once per FRAME id, and only the renderer's
			 * own loop advances that - which is not running yet. Without this
			 * the second render redraws the output quad over an empty target. */
			renderer._nodes.nodeFrame.update();
			/* The shadow map is drawn once and frozen, and the frame above
			 * drew it with no casters in it at all. */
			if ( sw ) shadowDirty();
			/* ...and the temporal AA starts again from nothing, as it did
			 * when this was the only frame behind the veil: the frame above
			 * took the first step of its jitter sequence and left an empty
			 * picture in its history. The jitter matters more than it
			 * looks - the sun's cascades are fitted to the jittered frustum
			 * and then frozen, so a different step is a different phase of
			 * shadow texels across every tree for the whole visit. A history
			 * of the wrong size is what makes the node restart it.
			 *
			 * It is still not the old frame to the texel: the cascade fit
			 * comes out 0.05% apart (-0.002088 against -0.002089 in the
			 * shadow matrix), which moves which leaf faces catch the sun and
			 * nothing else - 0.49/255 against a 0.37 floor, all of it in the
			 * crowns. Same map, same resolution, a different phase. */
			if ( traaNode && traaNode._historyRenderTarget ) {
				traaNode._jitterIndex = 0;
				traaNode._historyRenderTarget.setSize( 1, 1 );
			}
		}
		pipeline.render();
		const tDrawn = performance.now();
		unglass();
		unband();
		if ( unwarm ) unwarm();
		if ( ! sw && sun ) sun.shadow.needsUpdate = true;
		/* ...and then WAIT for it. Drawing it is not the same as having it:
		 * the renderer hands the pipelines to the GPU process and returns at
		 * once, Dawn compiles them there, and it is the first frame that USES
		 * them which pays - measured at 1.1 s, landing immediately after the
		 * veil lifted, so the page appeared and then froze for a second. The
		 * queue is drained here instead, where the boot bar is still up: the
		 * boot reads a second longer and the first visible frame is honest.
		 * ?drain=0 puts the freeze back, for measuring.                    */
		await drainGPU();
		bootbar.style.transition = '';
		if ( __q.get( 'warmlog' ) === '1' )
			console.info( 'warm frame: recorded in ' + Math.round( tDrawn - tWarm )
				+ ' ms' + ( PIPES ? ' (asked ' + Math.round( tAsked - tWarm ) + ', '
					+ pipesBuilt + ' pipelines built in ' + Math.round( tBuilt - tAsked ) + ')' : '' )
				+ ', GPU finished it ' + Math.round( performance.now() - tDrawn ) + ' ms later' );
		__perf.mark( 'first frame' );
	}
	if ( WARM === 'pass' ) {
		// kept for measurement: compile both passes over the whole scene. The
		// veil may drop before this settles, but the loop stays held off until
		// it does - a frame drawn through a borrowed renderer is a dead page.
		const job = ( async () => {
			compiling = true;
			try {
				await prePass.compileAsync( renderer );
				await scenePass.compileAsync( renderer );
			} finally { compiling = false; }
		} )();
		await Promise.race( [ job, new Promise( r => setTimeout( r, 5000 ) ) ] );
	}
	console.info( 'warm-up (' + WARM + ')', Math.round( performance.now() - t0 ) + ' ms' );
}

/* Compile a handful of objects for one pass' own target state. */
async function compileInto( passNode, objs, show = null ) {
	const rt = renderer.getRenderTarget(), mrt = renderer.getMRT();
	compiling = true;
	// compileAsync walks visible objects only, so whatever is being warmed
	// has to be shown - but only here, between `compiling = true` and the
	// frame loop being let go again, so no drawn frame ever contains it.
	const wasVisible = show ? show.visible : null;
	const sceneAt = sceneNo;
	if ( show ) show.visible = true;
	renderer.setRenderTarget( passNode.renderTarget );
	renderer.setMRT( passNode.getMRT() );
	try {
		for ( const o of objs ) await renderer.compileAsync( o, camera, scene );
		/* Wait for the compile to have actually HAPPENED before letting the
		 * loop go: compileAsync returns when the GPU process has been asked,
		 * and whatever frame draws next is the one that waits for it - which
		 * is how a batch of two objects turned into a 270 ms frame in the
		 * middle of the sweep. Drained here, the wait falls inside the window
		 * where no frame is drawn at all. Draining once for a whole
		 * window of warm batches instead of after each one was tried and
		 * measured the same to the millisecond - the wait is the compile,
		 * not the queue - so the simpler rule stands. */
		await drainGPU();
	}
	finally {
		/* ... unless somebody has taken the flat in the meantime. The warm
		 * captures `wasVisible` when a batch starts and puts it back when
		 * the batch ends, which stomped whatever happened in between: a
		 * scene change (guarded by `sceneAt`) and - since the hover - a
		 * storey being opened. A batch that began before the hover and
		 * ended after it set the flat straight back to hidden, which is the
		 * furniture vanishing a moment after the wall parted, and again on
		 * every floor-to-floor move. The flat belongs to the hover or the
		 * tour whenever either wants it; the warm only restores what it
		 * borrowed if neither does. */
		if ( show && sceneNo === sceneAt )
			show.visible = ( floorHot > 0 || floorBusy() ) ? true : wasVisible;
		renderer.setRenderTarget( rt );
		renderer.setMRT( mrt );
		compiling = false;
	}
}

/* ------------------------------------------- pipelines, side by side
 * What a FIRST visit actually waits for, and it is none of the things this
 * file measured for a month. Every rig booted a browser whose profile had
 * been wiped and called that cold - but the operating system keeps every
 * shader a GPU process has ever compiled in a cache of its own, outside the
 * profile (on macOS, `com.apple.metal` under the browser's bundle id), so
 * those boots found all ~300 of this page's pipelines already built and
 * took 2 s. With that cache empty, which is how every real visitor arrives:
 *
 *     warm frame: recorded in 1231 ms, GPU finished it 25868 ms later
 *
 * 29 s before the page appears, and another 20 s of half-second stalls
 * after it while the show flat's pipelines go the same way.
 *
 * The reason is ORDER, not volume. `device.createRenderPipeline()` returns
 * at once and the GPU process builds the pipeline when it reaches the call -
 * on its one device thread, the next call waiting behind it: 160 pipelines
 * at ~120 ms each, end to end. `createRenderPipelineAsync()` hands the same
 * build to the driver's worker threads, as many at a time as there are
 * cores. three.js has that path, but only inside `compileAsync()`, which
 * awaits each pipeline before it asks for the next - so it is the same
 * queue, one at a time (and `?warm=async`, which went through it, measured
 * 21 s of waiting for 94 pipelines).
 *
 * So the page asks for them itself. While `pipeJobs` is an array, every
 * pipeline the renderer creates is created through the async call and its
 * promise is kept here; three.js already skips an object whose pipeline has
 * not landed (`Pipelines.isReady`), so a frame rendered in that state builds
 * every node graph, asks for every pipeline and draws nothing. Await the
 * lot, render again, and that second frame finds them all. It is the render
 * path itself that asks, so the cache keys cannot disagree with the ones a
 * frame uses - which is what going through `compileAsync` got wrong.
 *
 * One hook, on the backend of a three.js that is vendored and pinned.
 * ?pipes=sync is the old path, for an A/B. `tools/hoverwait.cjs` with
 * `COLD=1` is the rig: it is the only one that empties the OS cache. */
const PIPES = __q.get( 'pipes' ) !== 'sync';
let pipeJobs = null, pipesHooked = false, pipesBuilt = 0, pipesPending = 0;
function pipesGather() {
	if ( ! pipesHooked ) {
		const be = renderer.backend, make = be.createRenderPipeline;
		be.createRenderPipeline = function ( renderObject, promises ) {
			const jobs = promises || pipeJobs, at = jobs ? jobs.length : 0;
			const out = make.call( this, renderObject, jobs );
			// how many are still being built, for anything that must not
			// show an object before its pipeline stands - see `floorTest`
			if ( jobs === pipeJobs && jobs ) for ( let i = at; i < jobs.length; i ++ ) {
				pipesPending ++;
				jobs[ i ].then( () => { pipesPending --; } );
			}
			return out;
		};
		pipesHooked = true;
	}
	if ( ! pipeJobs ) pipeJobs = [];
}
/* Wait for everything asked for so far, and stop gathering. A pipeline can
 * be asked for while the wait is on - nothing here stops a frame - so it
 * loops until a pass comes back empty. */
async function pipesSettled( onProgress = null ) {
	const jobs = pipeJobs;
	if ( ! jobs ) return;
	let done = 0, all = 0;
	while ( jobs.length ) {
		const j = jobs.splice( 0 );
		pipesBuilt += j.length; all += j.length;
		if ( onProgress ) for ( const p of j ) p.then( () => onProgress( ++ done, all ) );
		await Promise.all( j );
	}
	if ( pipeJobs === jobs ) pipeJobs = null;
}

const nextFrame = () => new Promise( r => requestAnimationFrame( r ) );
/* Wait until the GPU has actually done what has been submitted to it. The
 * WebGPU calls a frame makes are forwarded to the GPU process and return
 * before any of it has run, so a pipeline's real compile - tens of ms each,
 * a second for a sceneful - is paid by whatever frame first draws with it.
 * Draining lets a warm absorb that cost instead of the frame after it. */
const DRAIN = new URLSearchParams( location.search ).get( 'drain' ) !== '0';
async function drainGPU() {
	if ( ! DRAIN ) return;
	const q = renderer && renderer.backend && renderer.backend.device
		&& renderer.backend.device.queue;
	if ( q && q.onSubmittedWorkDone ) await q.onSubmittedWorkDone();
}

/* The show flat, warmed while the street sits idle: its maps first, then its
 * pipelines a few objects at a time with a frame between batches, so a drag
 * during the warm still answers. Nothing is drawn by this - the flat is
 * inside the building, and the frames in between only render if something
 * else owes one. Scene 2 waits on the same promise, so clicking it early
 * just joins the queue instead of starting a second one. */
/* The lab warms two objects at a time so a drag never waits. The page wants
 * the flat READY - the hover is dead until it is - so it takes bigger bites
 * and gets there in a few seconds instead of half a minute. */
/* ONE object at a time on the page, two in the lab. Each batch holds the
 * frame loop off while it compiles, so the batch size is the size of the
 * hitch the visitor feels: six objects at a time measured 130 ms hitches
 * and a hero at 33 fps, one object at a time 35 ms hitches and 42 fps for
 * the same total work. The lab has nobody watching and wants it over. */
const WARM_BATCH = + ( new URLSearchParams( location.search ).get( 'warmbatch' )
	|| ( document.body.dataset.embed === '1' ? 1 : 2 ) );
/* ...and the pacing BETWEEN batches, which turned out to be the whole cost.
 * The old loop waited two frames before each pass' compile and one after
 * every object: five frames an object, and at the ~32 fps the hero manages
 * while a warm is running that is 155 ms of waiting around some 35 ms of
 * work. Measured on the page: 51 objects in 8821 ms, of which ~7 s was the
 * page waiting for frames it had no reason to wait for - and the hover is
 * dead until this finishes, which is exactly what "after refresh i need too
 * much time to hover" was.
 *
 * It is a time BUDGET now: compile back to back until WARM_MS of wall clock
 * has gone, then yield exactly ONE frame. The hitch a visitor feels is the
 * budget plus however far the object in hand overshoots it - the same order
 * as a frame - and the warm is over in a fifth of the time.
 * ?warmms= sets the budget, ?warmidle=1 restores the old pacing for an A/B. */
const WARM_MS = + ( __q.get( 'warmms' ) ?? 8 );
/* ...and what the show flat's DRAW warm aims each of its frames at. The old
 * rule was one object a frame, which paid 51 presented frames of the street
 * (~13 ms each at the density the hero holds while warming) for 51 objects'
 * worth of work - 0.7 s of the hover's wait with nothing of the flat in it.
 * See `warmFlatDraw`. */
const DRAW_MS = + ( __q.get( 'drawms' ) ?? 60 );
/* How the show flat is warmed: 'draw' (the default on the page) draws every
 * object once behind the shut facade, which builds its pipeline and pays its
 * first-draw cost in one go; 'compile' is the old two-phase warm, kept for
 * measurement and for the lab, which has no hover to be ready for. */
const WARMLOG = __q.get( 'warmlog' ) === '1';
const WARM_DRAIN = __q.get( 'warmdrain' ) === '1';
const WARM2_HOW = __q.get( 'warm2' ) === 'compile' ? 'compile'
	: ( __q.get( 'warm2' ) === 'draw' ? 'draw' : ( EMBED ? 'draw' : 'compile' ) );
/* ...and the lab keeps the old pacing by default: it is a tool somebody
 * drags, it is render-on-demand, so `untilIdle` costs nothing while it sits
 * still and stops the warm stealing frames from a drag. The page is the one
 * with a visitor waiting on the hover. */
const WARM_IDLE = __q.has( 'warmidle' ) ? __q.get( 'warmidle' ) === '1' : ! EMBED;
/* Instancing used to be the first choice for any geometry repeated four or
 * more times. Measured, it is the wrong way round: an instanced geometry is
 * one draw call but it is also its own PIPELINE in each of the three passes
 * it appears in - pre-pass, beauty, shadow - and compiling pipelines is
 * what the boot spends its time on. Welding merges across geometries, not
 * just across copies, so a whole material becomes one draw and one pipeline.
 *
 * So the rule is not a count any more: weld whatever can be welded, and
 * instance only what cannot. The weld strips every attribute but position
 * and normal, so anything carrying texture coordinates - the downloaded
 * furniture - is exactly the set that still wants instancing.
 *
 * `?inst=<n>` restores the old count rule for an A/B. */
const INSTANCE_AT = + ( new URLSearchParams( location.search ).get( 'inst' ) || 0 );
/* a material the weld can swallow: no maps, so no UVs to lose */
const weldable = ( m ) => ! ( m.map || m.normalMap || m.roughnessMap || m.aoMap );

/* nothing is compiled over a frame somebody is waiting for */
async function untilIdle( limit = 900 ) {
	for ( let i = 0; i < limit && owed > 0; i ++ ) await nextFrame();
}

/* The flat can be DRAWN as soon as its pipelines exist - that is what the
 * hover waits for. `warmFlatDraw` after it only spares the first open its
 * one-off draw cost, so the hover is let go at the end of the compiles and
 * the rest of the warm runs behind it. */
let scene2Compiled = null, scene2CompiledDone = null;
const compiledPromise = () => scene2Compiled
	|| ( scene2Compiled = new Promise( r => { scene2CompiledDone = r; } ) );

/* The show flat, which arrives in its own file after the street.
 *
 * `scene.glb` was 12.52 MB and the first frame waited for all of it, while
 * 4.87 MB of that - 1048 nodes, 832 meshes and every one of the 33 embedded
 * textures - is the show flat, which stands inside the block with
 * `visible = false` until somebody hovers a storey. The partition is clean
 * enough to be safe: the two sides share no bufferView and no image, only
 * eight materials, which are simply written into both files. See
 * `tools/split_glb.py`, which also checks that every node and primitive of
 * the original turns up in exactly one of the two.
 *
 * So the street is 5.71 MB on the wire instead of 9.31, and the flat's
 * 3.60 MB is fetched behind the first frame - started by the HTML the
 * moment the street's own fetch resolves, so the two never compete for the
 * link. It has until the hover to arrive, which is the same second
 * `prepareScene2` was already spending on compiles; on anything but a very
 * slow connection it is there before the warm wants it.
 *
 * Folding it in is `batchInto( root, { flat: 1 } )` - the same weld, the
 * same instancing rule, the same baked pivots the street got - plus the two
 * things that only make sense once the flat exists: its materials are
 * split by job for the floor view, and the welded results are patched. */
async function loadFlat() {
	if ( FLAT_GONE ) return false;           // nothing to load: see FLAT_GONE
	// with the split off, the flat came in with the street and `optimise`
	// has already welded it into `groups.flat`
	if ( ! GLB_SPLIT ) { flatIn = true; return true; }
	if ( flatReady ) return flatReady;
	flatReady = ( async () => {
		const t0 = performance.now();
		let buf = null;
		const pre = window.__glbFlat;
		if ( pre ) {
			try { buf = await pre; } catch ( e ) {
				console.warn( 'the head\'s scene-flat.glb fetch failed, loading it again:', e );
			}
		}
		const gltf = buf
			? await new Promise( ( res, rej ) => glbLoader.parse( buf, './', res, rej ) )
			: await glbLoader.loadAsync( './scene-flat.glb' );
		window.__glbFlat = null;
		const tParsed = performance.now();
		/* Same order as the street's: the furniture's own glTF textures are
		 * the only ones nobody has set up, then the shaded materials go on
		 * by name, then it is welded. It has to be IN the scene before
		 * `batchInto` runs - the weld reads world matrices, and
		 * `groups.flat.attach()` resolves against the group's own. */
		sharpenTextures( gltf.scene );
		applyMaterials( gltf.scene, sceneMaterials );
		planSplitMaterials( gltf.scene );
		scene.add( gltf.scene );
		batchInto( gltf.scene, { flat: true } );
		gltf.scene.removeFromParent();           // the husk, now empty of meshes
		planSetupMaterials();                    // patch what the weld produced
		/* The flat is the decoder's last customer. */
		if ( glbDraco ) { glbDraco.dispose(); glbDraco = null; }
		flatIn = true;
		console.info( 'show flat: ' + Math.round( tParsed - t0 ) + ' ms to parse, '
			+ Math.round( performance.now() - tParsed ) + ' ms to fold in, '
			+ groups.flat.children.length + ' objects' );
		/* No `shadowDirty()` here on purpose. The map is drawn once and
		 * frozen, the flat folds in with `groups.flat` still hidden, and it
		 * is inside the block anyway - so nothing it could cast has changed.
		 * Asking for a fresh 4096 map would be half a second of boot spent
		 * redrawing the same picture. `setScene( 2 )` dirties it when the
		 * flat actually becomes something that casts. */
		return true;
	} )();
	return flatReady;
}

/* The neighbourhood, behind the first frame (owner, 2026-11-25: "too much
 * loading - lazy-load"). The blocks, lamps, beds and avenue trees round the
 * site are scene-hood.glb (tools/split_glb.py); the head asks for it once the
 * street file is down (`window.__glbHood`). Here it is parsed, its pipelines
 * built through the gate while it is still hidden - so no drawn frame pays a
 * compile - then welded into `groups.main` exactly as the street was, and the
 * frozen sun map is redrawn once so the blocks cast their shadows. With the
 * split off (`?glbsplit=0`) the one file already carried it. */
let hoodReady = null;
/* HOOD_FOLD (2026-11-27): the fold above held the frame loop through two
 * compileInto passes over ~340 loose meshes, each with a drain, and only then
 * welded them - the 0.8-1.2 s frozen frame in the first second of every ride.
 * Now it welds FIRST (a couple of dozen meshes) and lets the frames that draw
 * them ask for their pipelines side by side (`pipesGather`): an object whose
 * pipeline has not landed is simply not drawn, so nothing is held, and the
 * few materials no frame has built yet go in one a frame. The frozen sun map
 * is redrawn once they have all landed. `?hood=old` is the fold as it was,
 * exactly. (A `boot` arm - parse early, fold into the boot's warm frame - was
 * built and dropped: started at the street's parse, the file was still not
 * parsed when the warm frame came, 738 ms, so it never rode it.) */
const HOOD = __q.get( 'hood' ) === 'old' ? 'old' : 'after';
let hoodParse = null, hoodParsed = null, hoodFolded = false;
function hoodParseStart() {
	if ( hoodParse ) return hoodParse;
	hoodParse = ( async () => {
		const t0 = performance.now();
		let buf = null;
		if ( window.__glbHood ) {
			try { buf = await window.__glbHood; } catch ( e ) {
				console.info( 'the head\'s scene-hood.glb fetch failed, loading it again:', e.message );
			}
		}
		window.__glbHood = null;
		let gltf;
		try {
			gltf = buf
				? await new Promise( ( res, rej ) => glbLoader.parse( buf, './', res, rej ) )
				: await glbLoader.loadAsync( './scene-hood.glb' );
		} catch ( e ) {
			console.info( 'no neighbourhood file (scene-hood.glb):', e.message );
			return null;
		}
		hoodParsed = { gltf, t0, tParsed: performance.now() };
		return hoodParsed;
	} )();
	return hoodParse;
}
/* The weld itself, the same calls in the same order as the old fold. */
function hoodWeld( gltf ) {
	loadMapSet( 'hood' );
	applyMaterials( gltf.scene, sceneMaterials );
	scene.add( gltf.scene );
	gltf.scene.updateMatrixWorld( true );
	batchInto( gltf.scene, { main: true } );
	gltf.scene.removeFromParent();         // the husk, now empty of meshes
	hoodFolded = true;
}
function loadHood() {
	if ( ! GLB_SPLIT ) return Promise.resolve( false );
	if ( hoodReady ) return hoodReady;
	if ( HOOD !== 'old' && PIPES ) {
		hoodReady = ( async () => {
			const P = await hoodParseStart();
			if ( ! P ) return false;
			if ( hoodFolded ) return true;
			// one gatherer at a time: see pipesSettled
			while ( pipeJobs ) await nextFrame();
			const known = new Set();
			scene.traverse( ( o ) => { if ( o.isMesh && o.material ) known.add( o.material ); } );
			const before = new Set( groups.main.children );
			const tW = performance.now();
			hoodWeld( P.gltf );
			const tWelded = performance.now();
			const lots = new Map();
			for ( const o of groups.main.children ) {
				if ( before.has( o ) || ! o.material || known.has( o.material ) ) continue;
				if ( ! lots.has( o.material ) ) lots.set( o.material, [] );
				lots.get( o.material ).push( o );
				o.visible = false;
			}
			pipesGather();
			invalidate( 2 );
			await nextFrame(); await nextFrame();
			for ( const list of lots.values() ) {
				for ( const o of list ) o.visible = true;
				invalidate( 2 );
				await nextFrame(); await nextFrame();
			}
			// the shadow pass' pipelines for the new casters, asked for the same way
			shadowDirty();
			invalidate( 2 );
			await nextFrame(); await nextFrame();
			await pipesSettled();
			shadowDirty();                          // ...and the frozen map, with them in it
			invalidate( 4 );
			console.info( 'neighbourhood: ' + Math.round( P.tParsed - P.t0 ) + ' ms to arrive and parse, '
				+ Math.round( tWelded - tW ) + ' ms to weld, '
				+ Math.round( performance.now() - tWelded ) + ' ms to gather ' + lots.size + ' new materials (' + HOOD + ')' );
			return true;
		} )();
		return hoodReady;
	}
	hoodReady = ( async () => {
		const t0 = performance.now();
		let buf = null;
		if ( window.__glbHood ) {
			try { buf = await window.__glbHood; } catch ( e ) {
				console.info( 'the head\'s scene-hood.glb fetch failed, loading it again:', e.message );
			}
		}
		window.__glbHood = null;
		let gltf;
		try {
			gltf = buf
				? await new Promise( ( res, rej ) => glbLoader.parse( buf, './', res, rej ) )
				: await glbLoader.loadAsync( './scene-hood.glb' );
		} catch ( e ) {
			console.info( 'no neighbourhood file (scene-hood.glb):', e.message );
			return false;
		}
		const tParsed = performance.now();
		loadMapSet( 'hood' );
		applyMaterials( gltf.scene, sceneMaterials );
		const holder = new THREE.Group();
		holder.name = 'hood_holder';
		holder.visible = false;
		holder.add( gltf.scene );
		scene.add( holder );
		holder.updateMatrixWorld( true );
		await compileInto( prePass, [ holder ], holder );
		await compileInto( scenePass, [ holder ], holder );
		const tCompiled = performance.now();
		scene.add( gltf.scene );               // out of the hidden holder, matrices unchanged (both identity)
		holder.removeFromParent();
		batchInto( gltf.scene, { main: true } );
		gltf.scene.removeFromParent();         // the husk, now empty of meshes
		shadowDirty();
		invalidate( 4 );
		console.info( 'neighbourhood: ' + Math.round( tParsed - t0 ) + ' ms to arrive and parse, '
			+ Math.round( tCompiled - tParsed ) + ' ms to compile, '
			+ Math.round( performance.now() - tCompiled ) + ' ms to fold in' );
		return true;
	} )();
	return hoodReady;
}

function prepareScene2() {
	if ( FLAT_GONE ) return Promise.resolve( false );     // see FLAT_GONE
	if ( scene2Ready ) return scene2Ready;
	compiledPromise();                            // so the hover has it to wait on
	scene2Ready = ( async () => {
		const t0 = performance.now();
		/* ...and before any of it, the flat has to BE here: it is a second
		 * download now, and everything below reads `groups.flat`. */
		try { await loadFlat(); } catch ( e ) {
			console.error( 'the show flat did not load:', e );
			return scene2CompiledDone();
		}
		/* The hover waits for PIPELINES, not for pictures: a map that has not
		 * landed yet is a 1x1 default that gets swapped in underneath the
		 * same material with no pipeline rebuild. So when the boot has
		 * already drawn the flat, the hover is let go here - before the 24
		 * maps are so much as asked for - or a slow network would put the
		 * whole wait straight back on a page that is otherwise ready. */
		if ( flatWarmedInBoot ) scene2CompiledDone();
		await loadMapSet( true );
		const tMaps = performance.now();
		if ( ! groups.flat ) return scene2CompiledDone();
		const list = groups.flat.children.slice();
		const flat = groups.flat;
		let done = 0, i = 0;
		if ( WARM2_HOW !== 'compile' ) {
			/* Warming by DRAWING, which does both jobs at once. A pipeline is
			 * only half the cost - the first frame that draws a thing pays
			 * again - so the page used to compile all 51 objects (3.3 s) and
			 * then draw them all once behind the shut facade (2.5 s) for the
			 * same 51 pipelines. The draw alone builds them AND pays the
			 * first-draw cost, so it is the compile pass that is redundant,
			 * not the draw. ?warm2=compile puts the old two-phase warm back.
			 */
			// ...unless the boot drew it already, in which case the hover has
			// been armed since the veil lifted and only the twin is left
			if ( ! flatWarmedInBoot ) await warmFlatDraw();
			console.info( 'scene 2 warm: maps ' + Math.round( tMaps - t0 ) + ' ms, '
				+ ( flatWarmedInBoot ? 'drawn in the boot'
					: 'drawn in ' + Math.round( performance.now() - tMaps ) + ' ms' ) );
			scene2CompiledDone();                 // the hover may go now
			return makeTwin();                    // ...and the twin follows it
		}
		while ( i < list.length ) {
			const t = performance.now();
			do {
				const batch = list.slice( i, i + WARM_BATCH );
				if ( WARM_IDLE ) await untilIdle( EMBED ? 2 : 900 );
				await compileInto( prePass, batch, flat );
				if ( WARM_IDLE ) await untilIdle( EMBED ? 2 : 900 );
				await compileInto( scenePass, batch, flat );
				done += batch.length;
				i += batch.length;
			} while ( ! WARM_IDLE && i < list.length && performance.now() - t < WARM_MS );
			await nextFrame();
			if ( sceneNo !== 1 ) break;           // the flat is wanted for real now
		}
		console.info( 'scene 2 warm: maps ' + Math.round( tMaps - t0 ) + ' ms, '
			+ done + '/' + list.length + ' objects in ' + Math.round( performance.now() - tMaps ) + ' ms' );
		scene2CompiledDone();                     // the hover may go now
		if ( EMBED ) await warmFlatDraw();
		await makeTwin();
	} )();
	/* Either way - done or thrown - the hover stops waiting on it, and the
	 * density ladder forgets the frames the warm cost it. A warm that fails
	 * is a reason to let the pointer through, not to stay dead. */
	const release = ( e ) => {
		if ( e ) console.warn( 'the show flat\'s warm did not finish:', e );
		endWarm();
		if ( scene2CompiledDone ) scene2CompiledDone();
	};
	scene2Ready.then( () => release(), release );
	return scene2Ready;
}

/* ------------------------------------------------- scanned surface textures
 * Every map is made empty and filled when its image lands. three keeps a 1x1
 * default on the GPU until then and swaps the real texture in underneath the
 * same material, so the node graphs - and therefore the pipelines built from
 * them - are the same whether the image has arrived or not. The street's maps
 * are awaited before the first frame, because that frame is the shot people
 * compare against the photograph; the show flat's 24 maps are not fetched at
 * all until Scene 2 is wanted, which keeps ~4.9 MB and its decode out of the
 * boot. Columns: key, file, sRGB, belongs to the show flat.            */
const MAP_FILES = [
	[ 'asphaltDiff', 'asphalt_diff.webp', 1, 0 ],
	[ 'asphaltRough', 'asphalt_rough.webp', 0, 0 ],
	[ 'asphaltNor', 'asphalt_nor.webp', 0, 0 ],
	[ 'concreteDiff', 'concrete_diff.webp', 1, 0 ],
	[ 'concreteRough', 'concrete_rough.webp', 0, 0 ],
	[ 'concreteNor', 'concrete_nor.webp', 0, 0 ],
	[ 'railDiff', 'rail_diff.webp', 1, 0 ],
	[ 'railDisp', 'rail_disp.webp', 0, 0 ],
	[ 'hoodGrain', 'hood_grain.webp', 0, 2 ],   // the neighbours' granite speckle (data, grey); 2: arrives with scene-hood.glb
	[ 'parquetDiff', 'parquet_diff.webp', 1, 1 ],
	[ 'parquetRough', 'parquet_rough.webp', 0, 1 ],
	[ 'parquetNor', 'parquet_nor.webp', 0, 1 ],
	[ 'teakDiff', 'teak_diff.webp', 1, 1 ],
	[ 'teakRough', 'teak_rough.webp', 0, 1 ],
	[ 'teakNor', 'teak_nor.webp', 0, 1 ],
	[ 'leatherDiff', 'leather_diff.webp', 1, 1 ],
	[ 'leatherRough', 'leather_rough.webp', 0, 1 ],
	[ 'leatherNor', 'leather_nor.webp', 0, 1 ],
	[ 'planksDiff', 'planks_diff.webp', 1, 1 ],
	[ 'planksRough', 'planks_rough.webp', 0, 1 ],
	[ 'planksNor', 'planks_nor.webp', 0, 1 ],
	[ 'btileDiff', 'btile_diff.webp', 1, 1 ],
	[ 'btileRough', 'btile_rough.webp', 0, 1 ],
	[ 'btileNor', 'btile_nor.webp', 0, 1 ],
	[ 'bfloorDiff', 'bfloor_diff.webp', 1, 1 ],
	[ 'bfloorRough', 'bfloor_rough.webp', 0, 1 ],
	[ 'bfloorNor', 'bfloor_nor.webp', 0, 1 ],
	[ 'redDiff', 'redleather_diff.webp', 1, 1 ],
	[ 'redRough', 'redleather_rough.webp', 0, 1 ],
	[ 'redNor', 'redleather_nor.jpg', 0, 1 ],
	[ 'rugDiff', 'rug_diff.webp', 1, 1 ],
	[ 'rugRough', 'rug_rough.webp', 0, 1 ],
	[ 'rugNor', 'rug_nor.jpg', 0, 1 ],
];

const imgLoader = new THREE.ImageLoader().setPath( './tex/' );

/* ------------------------------------------------------------- sharpness
 * Everything in this scene is looked at edge-on: asphalt running away up
 * the street, a parquet floor under a camera that cranes over it, a facade
 * seen along its own length. That is exactly the case isotropic filtering
 * cannot do - it picks one mip for both axes and blurs the long one to
 * match the short one - so anisotropy is the difference between a texture
 * and a smear, and it is the cheapest quality there is. The scanned maps
 * asked for 8; the furniture that came in with the glTF asked for nothing
 * at all and got the loader's default of 1.                              */
const ANISO = + ( new URLSearchParams( location.search ).get( 'aniso' ) || 0 );
const maxAniso = () => ANISO
	|| ( renderer && renderer.getMaxAnisotropy ? renderer.getMaxAnisotropy() : 16 );

/* every texture a glTF material brought with it */
function sharpenTextures( root ) {
	const a = maxAniso();
	const seen = new Set();
	let n = 0;
	root.traverse( ( o ) => {
		if ( ! o.isMesh ) return;
		for ( const mat of ( Array.isArray( o.material ) ? o.material : [ o.material ] ) ) {
			if ( ! mat ) continue;
			for ( const k of Object.keys( mat ) ) {
				const t = mat[ k ];
				if ( ! t || ! t.isTexture || seen.has( t.uuid ) ) continue;
				seen.add( t.uuid );
				t.anisotropy = a;
				t.needsUpdate = true;
				n ++;
			}
		}
	} );
	return n;
}

function makeMaps() {
	const aniso = maxAniso();
	const m = {};
	for ( const [ key, file, srgb, interior ] of MAP_FILES ) {
		const t = new THREE.Texture();
		t.name = key;
		t.wrapS = t.wrapT = THREE.RepeatWrapping;
		t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
		t.anisotropy = aniso;
		t.userData.file = file;
		t.userData.interior = interior === 2 ? 'hood' : !! interior;
		m[ key ] = t;
	}
	return m;
}

function fillMap( t ) {
	if ( ! t.userData.pending ) t.userData.pending = new Promise( ( res ) => {
		imgLoader.load( t.userData.file, ( img ) => {
			t.image = img;
			t.needsUpdate = true;
			invalidate();
			res( t );
		}, undefined, () => res( t ) );
	} );
	return t.userData.pending;
}

/* every map that belongs to the street (false) or to the show flat (true) */
function loadMapSet( interior ) {
	return Promise.all( Object.values( maps )
		.filter( t => t && t.userData && t.userData.file && t.userData.interior === interior )
		.map( fillMap ) );
}

/* ---------------------------------------------------------------- materials */
function applyMaterials( root, M ) {
	const missing = new Set();
	root.traverse( ( o ) => {
		if ( ! o.isMesh ) return;
		const src = Array.isArray( o.material ) ? o.material[ 0 ] : o.material;
		const name = ( src && src.name || '' ).replace( /\.\d+$/, '' );
		const m = M[ name ];
		if ( m ) o.material = m; else missing.add( name );
		o.castShadow = true;
		o.receiveShadow = true;
	} );
	if ( missing.size ) console.warn( 'unmapped materials:', [ ...missing ] );
}

/* -------------------------------------------- batching: instance then merge */
/* BOTH blocks, by the names the real-plan build gives their envelopes:
 * every piece of block A starts `A_` and every piece of block B - the wing
 * included - `B_` (CONTRACT.md, "Exterior node names"). One level is one
 * floor plate across the whole L - the two blocks share the corridor - so
 * opening a level takes the storeys over it off both of them at once.
 * The podium, the terrace and the city are not caught and never cut. (The
 * old build's names - `winA_`, `loggia_*_f` - only ever caught block A,
 * because the storey cut then belonged to the one block the page sold.) */
const IS_TOWER = /^[AB]_/;
/* `?tower=0` leaves the block in `main`, where it was before the storey cut
 * - the A/B for what pulling it into its own clipping group costs the street
 * shot in draw calls and in pixels. With it off, clicking a floor opens the
 * top one, because there is nothing left to take the storeys away. */
const TOWER = __q.get( 'tower' ) !== '0';

/* The street's stand-in door leaves (CONTRACT "Street doors"): welded on
 * their own so the walk can take them away once the hall's own leaf is on
 * screen - two draws, materials the street already has. */
const IS_STREET_LEAF = /^podium_door_.+_leaf/;
/* MEASUREMENT ONLY: `?streetsplit=0` batches the street exactly as before the
 * walk (no leaf group, loggia panes welded in with the rest of the glass) -
 * the A/B for "the exterior render must not get worse". A walk on it keeps
 * the street's panes and stand-in leaves. */
const STREET_SPLIT = __q.get( 'streetsplit' ) !== '0';
/* ...and the punched windows' panes with them: the street's glass is a
 * mirror with nothing behind it, and from inside a room it was a blue slab in
 * the wall. A storey being walked has them swapped for clear panes. */
const IS_LG_GLASS = /^[AB]_(L\d\d)_(?:lg|wn|sl)\d+_(?:glass|lit)$/;
const IS_WN_GLASS = /^[AB]_L\d\d_(?:wn|sl)\d+_(?:glass|lit)$/;
const wnSrc = new Map();              // 'L03' -> the window panes' geometries, for the clear ones
const wnClear = new Map();            // 'L03' -> that storey's clear panes
let wnMat = null;
const lgAll = [];                     // the street's loggia panes, every storey, one mesh a material
const lgSrc = new Map();              // 'L03' -> material -> the panes' own geometries
const lgGlass = new Map();            // 'L03' -> that storey's panes, welded the first time a walk asks
/* Walking: the panes of every storey but the ones on screen. The first time,
 * each storey's panes are welded from the kept sources (a few milliseconds);
 * from then on it is visibility only. `null` puts the street's one mesh back. */
function lgSplit( hide ) {
	if ( ! lgAll.length ) return false;
	if ( hide && ! lgGlass.size ) for ( const [ lv, byM ] of lgSrc ) {
		const ms = [];
		for ( const [ mat, geos ] of byM ) {
			let g = null;
			try { g = BufferGeometryUtils.mergeGeometries( geos, false ); } catch ( e ) { g = null; }
			if ( ! g ) continue;
			const mesh = new THREE.Mesh( g, mat );
			mesh.name = 'loggia_glass_' + lv;
			mesh.castShadow = mesh.receiveShadow = true;
			mesh.frustumCulled = false;
			mesh.visible = false;
			groups.tower.add( mesh );
			ms.push( mesh );
		}
		lgGlass.set( lv, ms );
		const src = wnSrc.get( lv ), base = sceneMaterials && sceneMaterials.int_glass;
		if ( src && src.length && base ) {
			if ( ! wnMat ) { wnMat = base.clone(); wnMat.name = 'int_glass'; }
			let g = null;
			try { g = BufferGeometryUtils.mergeGeometries( src, false ); } catch ( e ) { g = null; }
			if ( g ) {
				const mesh = new THREE.Mesh( g, wnMat );
				mesh.name = 'window_clear_' + lv;
				mesh.frustumCulled = false;
				mesh.visible = false;
				groups.tower.add( mesh );
				wnClear.set( lv, mesh );
			}
		}
	}
	let changed = false;
	const all = ! hide;
	for ( const m of lgAll ) if ( m.visible !== all ) { m.visible = all; changed = true; }
	for ( const [ lv, ms ] of lgGlass ) {
		const on = !! hide && ! hide.has( lv );
		for ( const m of ms ) if ( m.visible !== on ) { m.visible = on; changed = true; }
	}
	for ( const [ lv, m ] of wnClear ) {
		const on = !! hide && hide.has( lv );
		if ( m.visible !== on ) { m.visible = on; changed = true; }
	}
	return changed;
}
function lgLevelOf( o ) {
	for ( let n = o; n; n = n.parent ) { const m = IS_LG_GLASS.exec( n.name || '' ); if ( m ) return m[ 1 ]; }
	return null;
}
function groupOf( o ) {
	if ( STREET_SPLIT ) for ( let n = o; n; n = n.parent ) if ( IS_STREET_LEAF.test( n.name || '' ) ) return 'leaf';
	for ( let n = o; n; n = n.parent ) {
		if ( /__cut\d*$/.test( n.name ) ) return 'cut';
		if ( /^flat/.test( n.name ) ) return 'flat';
		if ( TOWER && IS_TOWER.test( n.name ) ) return 'tower';
	}
	return 'main';
}

/* The batching itself, lifted out of `optimise` so it can be run a second
 * time over a model that arrived later.
 *
 * `scene.glb` used to carry the street and the show flat together, and the
 * flat is 4.87 MB of a 12.52 MB file that the first frame waits for and
 * does not draw: it stands inside the block with `visible = false` until
 * somebody hovers a storey. It is a separate download now
 * (`tools/split_glb.py`), and when it lands it has to be welded and grouped
 * exactly as the street was - same instancing rule, same per-material
 * merge, same pivots baked into the furniture. `only` restricts the walk to
 * one group so folding the flat in cannot touch what is already standing.
 *
 * Nothing in here creates a group or measures the scene; `optimise` keeps
 * both, because they are the parts that may only happen once. */
const TREE_TILE = + ( __q.get( 'treetile' ) ?? 50 );   // tree tile, metres (0: whole)
const IS_TILED = /^(foliage|foliage_b|bark)$/;
function batchInto( root, only ) {
	const byGeo = new Map();
	// In developer mode every piece of the flat stays its own object so it can
	// be picked and dragged. They are collected first and re-parented after
	// the walk: attaching during a traverse pulls children out from under it.
	const keepWhole = [];
	root.traverse( ( o ) => {
		if ( ! o.isMesh ) return;
		const g = groupOf( o );
		if ( only && ! only[ g ] ) return;
		if ( DEV && g === 'flat' ) { keepWhole.push( o ); return; }
		const k = g + '|' + o.geometry.uuid + '|' + o.material.uuid;
		if ( ! byGeo.has( k ) ) byGeo.set( k, { g, list: [] } );
		byGeo.get( k ).list.push( o );
	} );

	for ( const o of keepWhole ) {
		o.updateWorldMatrix( true, false );
		o.castShadow = o.receiveShadow = true;
		groups.flat.attach( o );
		/* Everything is modelled in world space, so each object's origin sits
		 * at the building's origin and a gizmo attached to it would appear
		 * nowhere near the piece. Re-centre the geometry on itself and move
		 * the object to match, so the pivot is the piece. Geometry is shared
		 * between linked duplicates, hence the clone. */
		o.geometry = o.geometry.clone();
		o.geometry.computeBoundingBox();
		const c = o.geometry.boundingBox.getCenter( new THREE.Vector3() );
		const wc = c.clone().applyMatrix4( o.matrixWorld );
		o.geometry.translate( - c.x, - c.y, - c.z );
		o.position.copy( wc );
		o.updateMatrixWorld( true );
	}

	const leftovers = [];
	for ( const { g, list } of byGeo.values() ) {
		// instance only what the weld cannot take (or, with ?inst=n, whatever
		// is repeated at least n times, which is how this used to work)
		const inst = INSTANCE_AT
			? list.length >= INSTANCE_AT
			: ( ! weldable( list[ 0 ].material ) && list.length >= 4 );
		if ( inst ) {
			const im = new THREE.InstancedMesh( list[ 0 ].geometry, list[ 0 ].material, list.length );
			list.forEach( ( m, i ) => {
				m.updateWorldMatrix( true, false );
				im.setMatrixAt( i, m.matrixWorld );
				m.removeFromParent();
			} );
			im.instanceMatrix.needsUpdate = true;
			im.castShadow = im.receiveShadow = true;
			im.frustumCulled = false;
			groups[ g ].add( im );
			// ...and if it is furniture, the floor view will want to grow
			// each of these out of the floor one at a time
			if ( g === 'flat' && planClass.get( im.material ) === PC_FURN )
				planHoldInstanced( im );
		} else {
			list.forEach( m => leftovers.push( [ g, m ] ) );
		}
	}

	// everything left gets welded into one mesh per material and group
	/* ...except the half of a door that hangs on its hinges, which gets a
	 * mesh of its own per material - the SAME material, so it costs three
	 * more draw calls and no new pipeline. Welded in with the linings it
	 * stands beside, a leaf could never be turned without taking its own
	 * doorframe round with it. See `doorRig`. */
	const byMat = new Map();
	/* The trees are welded in TILES of the plan - 50 m squares, each culled
	 * by its bounding sphere - not one mesh a material. One mesh for the
	 * whole city meant every pass, the walk's shadow redraw on every moving
	 * frame above all, submitted all 1.07 M triangles of crowns, almost all
	 * of them outside the cascade box or behind the camera. Same material,
	 * same attributes: ~60 more draws, no new pipeline. The neighbours
	 * (hood_*) stay whole: tiled they were 150 more draws for 0.3 M
	 * triangles and the lift ride got slower on draw submission.
	 * `?treetile=0` welds the trees whole, as before. */
	const tileOf = new Map();
	if ( TREE_TILE ) {
		const box = new THREE.Box3(), c = new THREE.Vector3();
		for ( const [ g, m ] of leftovers ) {
			const n = m.material.name || '';
			if ( g !== 'main' || ! IS_TILED.test( n ) ) continue;
			m.updateWorldMatrix( true, false );
			if ( ! m.geometry.boundingBox ) m.geometry.computeBoundingBox();
			box.copy( m.geometry.boundingBox ).applyMatrix4( m.matrixWorld ).getCenter( c );
			tileOf.set( m, Math.floor( c.x / TREE_TILE ) + ',' + Math.floor( c.z / TREE_TILE ) );
		}
	}
	leftovers.forEach( ( [ g, m ] ) => {
		const sw = doorSwingOf( planPieceName( m ) );
		/* A loggia's glass (`<B>_<LEVEL>_lg<NNN>_glass|lit`) is welded on
		 * its own: the interior glazes the loggia door with a leaf of its
		 * own, so a visitor walking a storey has the street's panes taken
		 * out of that storey and walks through the open door (CONTRACT
		 * "Interior <-> exterior seam" (d)). One more draw per material on
		 * the street, no new pipeline - the same material, the same group;
		 * the per-storey meshes a walk needs are welded only when a walk
		 * first asks (`lgSplit`), from the sources kept here. */
		const lg = g === 'tower' && STREET_SPLIT ? lgLevelOf( m ) : null;
		const tile = tileOf.get( m ) || null;
		const k = g + '|' + m.material.uuid + ( sw ? '|swing' : '' ) + ( lg ? '|lg' : '' ) + ( tile ? '|t' + tile : '' );
		if ( ! byMat.has( k ) )
			byMat.set( k, { g, mat: m.material, swing: !! sw, list: [], keys: [], lg, tile } );
		byMat.get( k ).list.push( m );
		byMat.get( k ).keys.push( sw );
	} );
	for ( const { g, mat, list, swing, keys, lg, tile } of byMat.values() ) {
		// A downloaded model carries texture coordinates, and the weld below
		// strips every attribute but position and normal - so anything with a
		// map stays its own draw call instead of being merged.
		if ( mat.map || mat.normalMap || mat.roughnessMap || mat.aoMap ) {
			// attach, not add: everything here is still parented to
			// BuildingRoot, which carries the block's rotation and its place
			// in the city. add() drops that matrix and the piece lands at its
			// own local coordinates, 70 m away over the street - which is
			// where the TV cabinet, the coffee table, the pot plants and the
			// bed cushions have all been standing, out of frame.
			list.forEach( m => {
				m.updateWorldMatrix( true, false );
				m.castShadow = m.receiveShadow = true;
				groups[ g ].attach( m );
			} );
			continue;
		}
		/* ...every attribute but position and normal, AND the baked colour,
		 * where the whole group carries one. The foliage is the only thing
		 * that does, and it is the one surface in the city whose shading is
		 * not in the shader: the per-leaf sun-and-shade that makes a crown
		 * read as a mass rather than as a heap of chips is baked into the
		 * mesh, because no shadow map at this frustum can resolve a leaf.
		 * Dropping it with the UVs cost nothing visible on the day and left
		 * every canopy painted one flat green. */
		const keepColor = list.every( ( m ) => !! m.geometry.getAttribute( 'color' ) );
		/* A whole row of bedrooms welds into one mesh, so a bed in it has no
		 * origin of its own left to be scaled about. The floor view needs
		 * one, so the furniture carries its own foot per vertex - added
		 * AFTER the strip above, and on the furniture only, which is a fifth
		 * of the flat's vertices and nothing anywhere else. */
		const foot = planClass.get( mat ) === PC_FURN;
		const geos = list.map( ( m ) => {
			m.updateWorldMatrix( true, false );
			const g = m.geometry.clone().applyMatrix4( m.matrixWorld );
			for ( const name of Object.keys( g.attributes ) )
				if ( name !== 'position' && name !== 'normal'
					&& ! ( keepColor && name === 'color' ) ) g.deleteAttribute( name );
			if ( foot ) planBakePivot( g );
			m.removeFromParent();
			return g;
		} );
		let merged = null;
		try { merged = BufferGeometryUtils.mergeGeometries( geos, false ); } catch ( e ) { /* keep separate */ }
		if ( merged ) {
			const mesh = new THREE.Mesh( merged, mat );
			mesh.castShadow = mesh.receiveShadow = true;
			mesh.frustumCulled = !! tile;
			if ( tile ) { merged.computeBoundingSphere(); mesh.name = 'tile_' + mat.name + '_' + tile; }
			groups[ g ].add( mesh );
			if ( swing ) doorStash( mesh, mat, geos, keys );
			if ( lg ) {
				mesh.name = 'loggia_glass';
				lgAll.push( mesh );
				list.forEach( ( m, i ) => {
					const lv = lgLevelOf( m );
					if ( ! lgSrc.has( lv ) ) lgSrc.set( lv, new Map() );
					const byM = lgSrc.get( lv );
					if ( ! byM.has( mat ) ) byM.set( mat, [] );
					byM.get( mat ).push( geos[ i ] );
					if ( IS_WN_GLASS.test( m.name || '' ) || ( m.parent && IS_WN_GLASS.test( m.parent.name || '' ) ) ) {
						if ( ! wnSrc.has( lv ) ) wnSrc.set( lv, [] );
						wnSrc.get( lv ).push( geos[ i ] );
					}
				} );
			}
		} else {
			list.forEach( m => groups[ g ].add( m ) );
		}
		// ...the swinging halves keep theirs: the rig re-welds them, four
		// doors of one flat at a time, round their own hinges - and so do
		// the loggias' panes, for `lgSplit`
		geos.forEach( g => { if ( merged && ! swing && ! lg ) g.dispose(); } );
	}
}

function optimise( root ) {
	/* Before any of it: the flat's materials are given one job each, so the
	 * floor view can take the furniture out of a mesh and leave the wall it
	 * shares a material with standing. See `planSplitMaterials`. */
	planSplitMaterials( root );
	const CLIPPED = { cut: true, tower: true };
	for ( const g of Object.keys( groups ) ) {
		groups[ g ] = CLIPPED[ g ] ? new THREE.ClippingGroup() : new THREE.Group();
		groups[ g ].name = 'group_' + g;
		scene.add( groups[ g ] );
	}
	groups.cut.clippingPlanes = [ cutPlane ];
	groups.cut.clipShadows = true;
	groups.tower.clippingPlanes = [ towerPlane ];
	groups.tower.clipShadows = true;
	/* The top-floor cells stand inside the block, so they answer to the
	 * storey cut as well as to their own: nested clipping groups union their
	 * planes and a fragment either plane drops is gone. */
	groups.tower.add( groups.cut );
	/* The real building's interiors, one group per resident level, all
	 * under one more clipping plane: `lvPlane` cuts the open level at the
	 * plan's section height. It rests at 1e4 like the others, and it is a
	 * plane from the start so an interior's pipelines are built clipped
	 * once and never rebuilt when the cut moves. */
	lvRoot = new THREE.ClippingGroup();
	lvRoot.name = 'group_levels';
	lvRoot.clippingPlanes = [ lvPlane ];
	lvRoot.clipShadows = true;
	scene.add( lvRoot );
	batchInto( root );
	// the sweep runs from just above the roof to just below the flat's slab
	const bb = new THREE.Box3().setFromObject( groups.cut );
	cutTop = bb.max.y + 0.3;
	cutBottom = bb.min.y - 0.05;
	/* Where the storey cut starts from: clear of the block's own parapet, so
	 * the first frame of the sweep has taken nothing off yet. `groups.cut`
	 * is a child of the tower now, so this box is the whole of block A. */
	const tb = new THREE.Box3().setFromObject( groups.tower );
	towerTop = tb.max.y + 0.5;

	let draws = 0;
	const tally = {};
	scene.traverse( ( o ) => {
		if ( ! o.isMesh ) return;
		draws ++;
		const n = ( o.material && o.material.name ) || '?';
		tally[ n ] = ( tally[ n ] || 0 ) + ( o.isInstancedMesh ? o.count : 1 );
	} );
	console.info( 'draw objects after batching:', draws, tally );
	window.__scene = scene; window.__camera = camera; window.__renderer = renderer;
	window.__invalidate = invalidate;
}

/* ----------------------------------------------- reference plan overlay */
function buildPlanOverlay() {
	const f = meta && meta.flat;
	if ( ! f ) return;
	const O = new THREE.Vector3( ...f.origin );
	const ex = new THREE.Vector3( ...f.ex );
	const ey = new THREE.Vector3( ...f.ey );
	// `plan_size`, not `size`: the flat is deeper than the plan was rectified
	// to - its entrance wall moved back to meet the back line's - and laying
	// the plan over the whole of it would stretch every room off its metres.
	const ps = f.plan_size || f.size;
	const W = ps[ 0 ], D = ps[ 1 ];
	// above the cut walls, so from the Top view it reads as a transparency
	// laid over the whole flat rather than a rug the furniture stands on
	O.y = f.floor + f.cut + 0.25;
	const p00 = O.clone();
	const p10 = O.clone().addScaledVector( ex, W );
	const p01 = O.clone().addScaledVector( ey, D );
	const p11 = p10.clone().addScaledVector( ey, D );
	const g = new THREE.BufferGeometry();
	g.setAttribute( 'position', new THREE.Float32BufferAttribute( [
		...p00.toArray(), ...p10.toArray(), ...p11.toArray(), ...p01.toArray() ], 3 ) );
	// the texture's top row is the facade (v = 0), so it maps to p00 - p10
	g.setAttribute( 'uv', new THREE.Float32BufferAttribute( [ 0,1, 1,1, 1,0, 0,0 ], 2 ) );
	g.setAttribute( 'normal', new THREE.Float32BufferAttribute( [ 0,1,0, 0,1,0, 0,1,0, 0,1,0 ], 3 ) );
	g.setIndex( [ 0, 2, 1, 0, 3, 2 ] );
	// 2.9 MB that only Scene 2's plan checkbox ever shows, so the texture is
	// made empty here and its image fetched the first time the plan goes on.
	const tex = planTex = new THREE.Texture();
	tex.colorSpace = THREE.SRGBColorSpace;
	const m = new THREE.MeshBasicNodeMaterial( { transparent: true, side: THREE.DoubleSide } );
	m.name = 'plan_overlay';
	m.colorNode = texture( tex, planUV() );
	m.opacityNode = texture( tex, planUV() ).a.mul( 0.92 );
	m.depthWrite = false;
	planOverlay = new THREE.Mesh( g, m );
	planOverlay.renderOrder = 10;
	planOverlay.frustumCulled = false;
	planOverlay.visible = false;
	scene.add( planOverlay );
}

// the render's unit is the opposite hand to ours, so the plan is flipped
// along the facade by default; the checkbox turns that off
const planFlip = uniform( 1.0 );
function planUV() {
	return vec2( mix( uv().x, oneMinus( uv().x ), planFlip ), uv().y );
}

function setPlan( on ) {
	if ( ! planOverlay ) return;
	planOverlay.visible = on && sceneNo === 2;
	if ( planOverlay.visible && planTex && ! planTex.image ) {
		new THREE.ImageLoader().load( './plan_overlay.webp', ( img ) => {
			planTex.image = img;
			planTex.needsUpdate = true;
			invalidate();
		} );
	}
	invalidate();
}

/* ------------------------------------------------------- developer mode */
function flatOf( p ) {
	const f = meta && meta.flat;
	if ( ! f ) return null;
	const dx = p.x - f.origin[ 0 ], dz = p.z - f.origin[ 2 ];
	return {
		x: dx * f.ex[ 0 ] + dz * f.ex[ 2 ],
		y: dx * f.ey[ 0 ] + dz * f.ey[ 2 ],
		z: p.y - f.floor,
	};
}

function devReport() {
	const sel = $( 'dev_sel' );
	const pos = $( 'dev_pos' );
	if ( ! picked ) {
		sel.textContent = 'click a piece to select it';
		pos.textContent = '';
		return;
	}
	sel.textContent = picked.name || '(unnamed)';
	const fp = flatOf( picked.getWorldPosition( new THREE.Vector3() ) );
	const mat = picked.material && picked.material.name;
	pos.textContent = fp
		? `flat  x ${fp.x.toFixed( 3 )}   y ${fp.y.toFixed( 3 )}   z ${fp.z.toFixed( 3 )}\n` +
		  `turn  ${( picked.rotation.y * 180 / Math.PI ).toFixed( 1 )}\u00b0\n` +
		  `material  ${mat || '-'}`
		: '';
}

function devSelect( o ) {
	picked = o;
	invalidate();
	if ( gizmo ) {
		if ( o ) gizmo.attach( o ); else gizmo.detach();
	}
	devReport();
}

function initDev() {
	$( 'dev' ).hidden = false;
	gizmo = new TransformControls( camera, renderer.domElement );
	gizmo.setSpace( 'local' );
	gizmo.addEventListener( 'dragging-changed', ( e ) => {
		controls.enabled = ! e.value && mode === 'orbit';
		if ( ! e.value && picked ) {
			const fp = flatOf( picked.getWorldPosition( new THREE.Vector3() ) );
			moved.set( picked.name || picked.uuid, {
				x: +fp.x.toFixed( 3 ), y: +fp.y.toFixed( 3 ), z: +fp.z.toFixed( 3 ),
				turn: +( picked.rotation.y * 180 / Math.PI ).toFixed( 1 ),
			} );
		}
		devReport();
	} );
	gizmo.addEventListener( 'objectChange', () => { devReport(); shadowDirty(); invalidate(); } );
	scene.add( gizmo.getHelper ? gizmo.getHelper() : gizmo );

	// the gizmo lights its axes under the pointer, which only shows if the
	// frame is redrawn - developer mode therefore draws while the mouse moves
	renderer.domElement.addEventListener( 'pointermove', () => invalidate( 2 ) );

	const ray = new THREE.Raycaster();
	const ndc = new THREE.Vector2();
	let downAt = null;
	renderer.domElement.addEventListener( 'pointerdown', ( e ) => { downAt = [ e.clientX, e.clientY ]; } );
	renderer.domElement.addEventListener( 'pointerup', ( e ) => {
		if ( ! downAt ) return;
		const slid = Math.hypot( e.clientX - downAt[ 0 ], e.clientY - downAt[ 1 ] );
		downAt = null;
		if ( slid > 4 || ( gizmo && gizmo.dragging ) ) return;
		const r = renderer.domElement.getBoundingClientRect();
		ndc.set( ( e.clientX - r.left ) / r.width * 2 - 1, - ( ( e.clientY - r.top ) / r.height ) * 2 + 1 );
		ray.setFromCamera( ndc, camera );
		const hits = ray.intersectObjects( [ groups.flat, groups.main, groups.tower ], true )
			.filter( h => h.object.isMesh && h.object.visible );
		devSelect( hits.length ? hits[ 0 ].object : null );
	} );
	addEventListener( 'keydown', ( e ) => {
		if ( ! gizmo ) return;
		if ( e.key === 'w' || e.key === 'W' ) gizmo.setMode( 'translate' );
		if ( e.key === 'e' || e.key === 'E' ) gizmo.setMode( 'rotate' );
		if ( e.key === 'r' || e.key === 'R' ) gizmo.setMode( 'scale' );
		if ( e.key === 'Escape' ) devSelect( null );
	} );
	$( 'dev_dump' ).addEventListener( 'click', () => {
		const lines = [ ...moved.entries() ].map( ( [ k, v ] ) =>
			`${k}:  x ${v.x}  y ${v.y}  z ${v.z}  turn ${v.turn}` );
		const text = lines.length ? lines.join( '\n' ) : 'nothing moved yet';
		console.info( '--- moved pieces, in flat metres ---\n' + text );
		if ( navigator.clipboard ) navigator.clipboard.writeText( text ).catch( () => {} );
		$( 'dev_pos' ).textContent = lines.length
			? `copied ${lines.length} change(s)` : 'nothing moved yet';
	} );
	setMode( 'orbit' );
}

/* ----------------------------------------------------------- the hero
 * On the landing page the solved shot is not a picture, it turns. Orbit is
 * live from the first frame with the lens shift left on, so verticals stay
 * vertical while you drag; the wheel is left to the page, because a landing
 * page whose hero swallowed the scroll would trap you in it; and panning is
 * off, so the building can be turned but never lost. The swing is bounded
 * around whatever shot the scene is currently holding - the street shot or
 * the flat - and the lower bound is worked out from the ground rather than
 * guessed, so the limits never snap the camera the moment they are applied.
 * ----------------------------------------------------------- */
function embedLimits() {

	if ( ! controls ) return;
	const t = orbitTarget();
	const v = camera.position.clone().sub( t );
	const d = v.length();
	if ( d < 1e-3 ) return;
	const az = Math.atan2( v.x, v.z );
	const po = Math.acos( THREE.MathUtils.clamp( v.y / d, - 1, 1 ) );
	const swing = sceneNo === 2 ? 0.85 : 0.33;      // radians either way
	const rise = sceneNo === 2 ? 0.50 : 0.30;
	// how far down the camera may swing before it is under the pavement
	const floorY = sceneNo === 2 ? t.y - d * 0.05 : 1.2;
	const poFloor = Math.acos( THREE.MathUtils.clamp( ( floorY - t.y ) / d, - 1, 1 ) );
	controls.target.copy( t );
	controls.minAzimuthAngle = az - swing;
	controls.maxAzimuthAngle = az + swing;
	controls.minPolarAngle = Math.min( po, Math.max( 0.10, po - rise ) );
	controls.maxPolarAngle = Math.max( po, Math.min( poFloor, po + rise * 0.5 ) );
	controls.minDistance = controls.maxDistance = d;
	controls.update();

}

/* Flying is off while the hero is scrolled away: the page owns the
 * keyboard then. site.js flips this through window.LP. */
let flyAllowed = true;

/* Compiling a pipeline is not the whole cost of showing something: the first
 * frame that actually DRAWS it pays again - 1.2 s of it the first time a
 * storey opened, and a quarter of a second more the first time the pointer
 * crossed to another floor, because that is when the second flat was cloned.
 * So both are done here instead, while the wall is still shut: the flats are
 * placed on a storey with the x-ray closed - which leaves them behind a
 * solid facade, invisible - shown for two frames, and put away. The visitor
 * sees nothing; the GPU has built everything by the time a floor is hovered. */
/* The second flat, made once the hover has been let go. `clone( true )`
 * shares three.js geometry and materials with the original, so it is node
 * allocation and nothing else - about 0.3 s of it - and it is not wanted
 * until a visitor crosses from one storey to ANOTHER, which is a second
 * after the first hover at the very earliest. Made in front of the arm it
 * was 0.3 s of a wait the user feels; made behind it, the first
 * floor-to-floor move still finds it standing ready. */
async function makeTwin() {
	await nextFrame();                            // not in the arm's own frame
	const t = performance.now();
	if ( floorFlat( 1 ) )
		console.info( 'twin flat made in ' + Math.round( performance.now() - t ) + ' ms' );
}

async function warmFlatDraw() {
	const b = meta && meta.block && meta.block.floors;
	if ( ! b || ! groups.flat ) return;
	const t0 = performance.now();
	/* Only the FIRST flat, and only the first is drawn. A clone shares
	 * three.js geometry and materials with its original, so every pipeline
	 * the twin would build is already built by the original's draw: drawing
	 * it was half of this warm and bought nothing (?warmtwin=1 for an A/B).
	 *
	 * MAKING it is not free either - `clone( true )` is ~0.3 s of node
	 * allocation - and that used to be paid right here, in front of the
	 * thing the hover is waiting for. The twin is not wanted until a visitor
	 * crosses from one storey to another, which is a second after the first
	 * hover at the very earliest, so it is made after the arm instead
	 * (`makeTwin` below). */
	const both = [ floorFlat( 0 ) ].filter( Boolean );
	const drawn = __q.get( 'warmtwin' ) === '1' ? both : both.slice( 0, 1 );
	const was = both.map( f => [ f.visible, f.position.y ] );
	for ( const f of drawn ) {
		f.position.y = ( 3 - b.n ) * b.h;         // a storey in the middle
		f.visible = true;
	}
	/* A FEW objects at a time, each chunk drained before the next. Drawing
	 * the whole flat in one frame warmed it in one 1.0 s stall - a freeze in
	 * the middle of the hero, measured at second 7 - because every pipeline
	 * the draw needed was compiled inside that one frame. Chunked and
	 * drained it is the same total work in ~`DRAW_CHUNK`-object pieces with
	 * a frame between them, so the sweep keeps moving while it happens. */
	/* ONE object a frame, and no waiting for the GPU in between. Measured
	 * over the whole warm (51 objects, `?warmlog=1` prints every chunk):
	 *
	 *   2 at a time, drained    3111 ms total   115 ms between frames
	 *   8 at a time, drained    1642 ms         250-300 ms   <- a visible freeze
	 *   8 at a time, no drain   1220 ms         140-240 ms
	 *   2 at a time, no drain   1332 ms          51 ms mean
	 *   1 at a time, no drain   1481 ms          29 ms mean, 73 worst   <- this
	 *
	 * The drain is what the two-phase warm needed, because a COMPILE only
	 * asks the GPU process for a pipeline and the next frame to draw with it
	 * pays. A draw is not like that: it submits the work, Dawn builds the
	 * pipeline on its own threads, and the page can go on submitting the
	 * next object meanwhile - so waiting for the queue only idles the page.
	 * Chunking bigger buys nothing either: the cost is per object, and all a
	 * big chunk does is collect several objects' worth of it into one gap
	 * the hero visibly freezes in. ?drawchunk= and ?warmdrain=1 restore the
	 * other rows of that table. */
	/* ...but ONE object a frame is not the answer either, because a presented
	 * frame is not free: at the density the hero holds while it is warming,
	 * the street costs ~13 ms to draw whether or not a piece of furniture
	 * rode along with it, and 51 of those is 0.7 s of the wait that has
	 * nothing to do with the flat. Measured end to end (`tools/hoverwait.cjs`),
	 * same machine, same boot: 1 a frame 1697 ms, 4 a frame 1196 ms.
	 *
	 * So the chunk AIMS at a frame time rather than at a count. It cannot be
	 * a straight time budget the way the compile warm's is - showing an
	 * object costs nothing, the cost is inside the `pipeline.render()`
	 * afterwards, so a loop that filled a budget by the clock would put all
	 * 51 into the first frame. It is a feedback loop instead: each chunk is
	 * sized from what the last one actually measured, so the cheap objects
	 * ride together and an expensive one - the scanned pot plants are 107k
	 * triangles each and measure 60-95 ms - pulls the next chunk back down
	 * to one. Capped at 6, because a chunk is also the size of the hitch.
	 * ?drawms= aims it, ?drawchunk= pins a count for the old A/B. */
	const chunkSize = + ( __q.get( 'drawchunk' ) || 0 );
	let aim = 1;
	const kids = drawn.flatMap( f => f.children );
	const vis = kids.map( o => o.visible );
	for ( const o of kids ) o.visible = false;
	/* The flat's pipelines are built side by side as well - see
	 * `pipesGather`. On a first visit they were the other half of the wait:
	 * 150 of them, one behind another on the GPU process' device thread,
	 * every one a frame the hero stood still for - twenty seconds of stalls
	 * of up to two seconds each, AFTER the page had appeared. Asked for
	 * through the async call they are built on the driver's worker threads
	 * and no frame waits for any of them. The loop below is unchanged and
	 * now only does the half that was always the page's own - turning each
	 * object's node graph into WGSL, a chunk a frame - and draws nothing,
	 * because an object whose pipeline has not landed is skipped. */
	if ( PIPES ) pipesGather();
	for ( let i = 0; i < kids.length; ) {
		const chunk = kids.slice( i, i + ( chunkSize || aim ) );
		chunk.forEach( ( o, j ) => { o.visible = vis[ i + j ]; } );
		i += chunk.length;
		const tc = performance.now();
		invalidate( 2 );
		await nextFrame();
		const tf = performance.now();
		if ( WARM_DRAIN ) await drainGPU();
		if ( WARMLOG ) console.info( 'draw chunk ' + chunk.length + ': frame '
			+ Math.round( tf - tc ) + ' ms, drain ' + Math.round( performance.now() - tf ) + ' ms' );
		// what the next chunk should be, from what this one cost
		aim = Math.max( 1, Math.min( 6,
			Math.round( chunk.length * DRAW_MS / Math.max( 8, tf - tc ) ) ) );
		for ( const o of chunk ) o.visible = false;
		if ( sceneNo !== 1 || floorHot > 0 ) break;   // it is wanted for real
	}
	if ( PIPES ) {
		const tp = performance.now();
		await pipesSettled();
		/* ...and then every object is drawn once for real, six a frame:
		 * with its pipeline standing that is a first draw and nothing more,
		 * and it is what `floorArmed` has always meant - the flat can be
		 * shown and all of it will be there. */
		const wanted = () => sceneNo !== 1 || floorHot > 0;
		for ( let i = 0; i < kids.length && ! wanted(); i += 6 ) {
			const chunk = kids.slice( i, i + 6 );
			chunk.forEach( ( o, j ) => { o.visible = vis[ i + j ]; } );
			invalidate( 2 );
			await nextFrame();
			for ( const o of chunk ) o.visible = false;
		}
		if ( WARMLOG ) console.info( 'flat pipelines settled and drawn '
			+ Math.round( performance.now() - tp ) + ' ms after the last was asked for' );
	}
	kids.forEach( ( o, i ) => { o.visible = vis[ i ]; } );
	/* Only put the flats back where they were if nothing has asked for them
	 * in the meantime - a storey opened mid-warm owns the flat now, and
	 * restoring over it is the furniture vanishing a moment after the wall
	 * parted (the same trap `compileInto` guards). */
	if ( sceneNo === 1 && ! ( floorHot > 0 || floorBusy() ) )
		both.forEach( ( f, i ) => { f.visible = was[ i ][ 0 ]; f.position.y = was[ i ][ 1 ]; } );
	invalidate();
	console.info( 'flat first draw warmed in ' + Math.round( performance.now() - t0 ) + ' ms' );
}

/* ---------------------------------------------------------- the floor map
 * Every storey of the street front is a band you can hover: the whole floor
 * lights in the brand's amber at .6, laid 8 cm proud of the facade so it
 * never fights the wall for depth. The bands are plain quads in the
 * building's own frame - `origin` and `ex` from the flat's meta, `base`,
 * `h` and `len` from the block - and they are there to be hit tested, so
 * they carry opacity 0 until the pointer finds one.
 *
 * Storey 1 is the podium terrace and has no flats, so the map runs from 2
 * to the roof. What the page does with the hover is the page's business:
 * the scene only says which floor it is, through `lp:floor`.
 * ------------------------------------------------------------------ */
const FLOOR_AMBER = 0xe5af69;
/* The opening carries no glass of its own now: what says "this floor" is the
 * light inside it. The bands stay in the scene at zero opacity because they
 * are what the pointer is tested against. */
const FLOOR_LIT = 0.0;
/* How hard the lamp inside an opened storey burns. The rooms stand in the
 * building's own shadow, so this is what makes a floor read as lit from
 * within rather than merely uncovered - the user asked for "very big light",
 * and at a tenth of this it looked like daylight through a hole. */
const FLOOR_GLOW = + ( __q.get( 'glow' ) ?? 2.0 );
/* Seconds the wall takes to part, and to shut. `?open=` stretches it, which
 * is the only way to LOOK at the dissolve - at 0.4 s the whole of it is six
 * frames and a screenshot never lands inside it. */
const FLOOR_OPEN = + ( __q.get( 'open' ) ?? 0.40 );
/* How fast the storey's wall DISSOLVES, against how fast it parts. The floor
 * answers the pointer two ways at once: the parting line travels up and down
 * from the middle of the storey as it always did, and over the whole of that
 * floor - not just the band - the wall fades, so the rooms and the lamps
 * come up through it while the opening grows. At 1 the fade is tied to the
 * open; above it the wall is see-through before the line has got anywhere,
 * and by 1.6 there is nothing left for the line to part. `?fade=` tunes it,
 * `?fade=0` is the old hard cut on its own. */
const FLOOR_FADE = + ( __q.get( 'fade' ) ?? 1.15 );
const FLOOR_ARM_MS = 2500;   // ...and the longest the hover will wait to arm
const FLOOR_ARM_CAP = 20000; // ...unless pipelines are still being built: see `floorTest`
const floorBusy = () => floorSlots.some( s => s.open > 0 || s.want > 0 );
let floorMap = null, floorHot = 0, xray = null, floorArmed = false, floorArming = false;

function buildFloorMap() {
	const b = meta && meta.block && meta.block.floors;
	const f = meta && meta.flat;
	if ( ! b || ! f ) return;
	const o = new THREE.Vector3( ...f.origin );
	const ex = new THREE.Vector3( ...f.ex ).normalize();
	const ey = new THREE.Vector3( ...f.ey ).normalize();
	const up = new THREE.Vector3( 0, 1, 0 );
	// +x along the street, +y up, the quad's normal out of the facade
	const basis = new THREE.Matrix4().makeBasis( ex, up, ex.clone().cross( up ) );
	const quat = new THREE.Quaternion().setFromRotationMatrix( basis );
	floorMap = new THREE.Group();
	floorMap.name = 'floor_map';
	// the gable: the same storey, on the end wall that stands behind the
	// hero's type, so the floor can be taken by its corner as well as by
	// its front. Hit testing is two sided, so the facing does not matter.
	const gableQuat = new THREE.Quaternion().setFromRotationMatrix(
		new THREE.Matrix4().makeBasis( ey, up, ey.clone().cross( up ) ) );
	for ( let n = 2; n <= b.n; n ++ ) {
		const y = b.base + ( n - 1 ) * b.h + b.h * 0.5;
		const band = ( geo, pos, q ) => {
			const mesh = new THREE.Mesh( geo, new THREE.MeshBasicNodeMaterial( {
				color: FLOOR_AMBER, transparent: true, opacity: 0,
				depthWrite: false, side: THREE.DoubleSide } ) );
			mesh.position.copy( pos ).setY( y );
			mesh.quaternion.copy( q );
			mesh.renderOrder = 3;
			mesh.frustumCulled = false;
			mesh.visible = false;            // until it lights - see floorApply
			mesh.userData.floor = n;
			floorMap.add( mesh );
		};
		band( new THREE.PlaneGeometry( b.len, b.h ),
			o.clone().addScaledVector( ex, b.len * 0.5 ).addScaledVector( ey, - 0.08 ),
			quat );
		band( new THREE.PlaneGeometry( b.depth || 18, b.h ),
			o.clone().addScaledVector( ex, - 0.08 )
				.addScaledVector( ey, ( b.depth || 18 ) * 0.5 ),
			gableQuat );
	}
	scene.add( floorMap );
	buildFloorGlass();
}

/* --------------------------------------------------------- the glazing
 * A storey whose wall has gone is a hole in a building, and a hole reads as
 * damage. What the hover wants is the opposite: the floor should read as
 * GLAZED - the wall replaced by one pane, the rooms behind it, the sky on
 * it. So a sheet of glass is laid where the wall stood, 8 cm proud of the
 * facade, and it carries the four things that make a pane read as glass
 * rather than as a blue rectangle:
 *
 *  1  the sky mirrored off it, by Fresnel - weak face on, strong at the
 *     grazing angles a street front is actually seen from, which is why
 *     real glazing goes pale along a facade and dark straight ahead. And
 *     not only the sky: below the horizon it mirrors the far side of the
 *     avenue, and the line between the two falls inside the storey.
 *  2  the sun caught in it. The sky sampled here is the LIGHT sky, the one
 *     the building's own windows already reflect, so every pane in the
 *     frame agrees - and that one carries no disc, so the glint is put back
 *     analytically: a tight lobe and its halo.
 *  3  the pane itself - the green of float glass seen through it, the bow
 *     every sealed unit has, and the rain runs and the dust along its foot.
 *  4  a MODULE. 47 m of unbroken sky has no scale and reads as haze over a
 *     hole; a joint every metre and a half, with the pane between each pair
 *     bowed its own way, is what makes it a facade.
 *
 * It is one blended quad per opening, drawn over rooms that are already in
 * the frame, so it costs its own fill and nothing else: no transmission
 * pass, no second render of what stands behind it.
 * ------------------------------------------------------------------ */
/* `f0` is an *effective* normal incidence reflectance, not the 4.3% of a
 * single air/glass interface. A sealed clear unit measures about 15%,
 * because the light meets four surfaces - but this pane exists to be seen
 * THROUGH, and at the oblique angle the street front is seen from, 15/90
 * puts so much sky on it that the rooms the hover is there to show go
 * behind a mirror. So it is a coated pane: the same Fresnel curve, lower at
 * both ends. `?gf0=` and `?gf90=` move them. */
const GLASS_F0 = uniform( + ( __q.get( 'gf0' ) ?? 0.17 ) );
const GLASS_F90 = uniform( + ( __q.get( 'gf90' ) ?? 0.74 ) );
/* ...and what the glass itself takes out of the room behind it. Float glass
 * is green on the way through and a window is never quite invisible; this is
 * the only part of the pane that is there at every angle. */
const GLASS_BODY = uniform( + ( __q.get( 'gbody' ) ?? 0.07 ) );
const GLASS_GREEN = uniform( new THREE.Vector3( 0.46, 0.64, 0.58 ) );
const GLASS_ENV = uniform( + ( __q.get( 'genv' ) ?? 1.0 ) );    // the sky on it
const GLASS_BOW = uniform( + ( __q.get( 'gbow' ) ?? 0.055 ) );  // a sealed unit's swell
const GLASS_SUN = uniform( + ( __q.get( 'gsun' ) ?? 1.1 ) );    // the sun caught in it
const GLASS_GRIME = uniform( + ( __q.get( 'ggrime' ) ?? 0.40 ) );
/* How wide a pane is, in metres, and how dark the joint between two of them
 * reads. A 47 m sheet of unbroken sky is the one thing that gives the trick
 * away - it has no scale, so the eye files it as haze over a hole rather
 * than as glazing - and a facade is never one sheet anyway: it is a module,
 * silicone-jointed, every pane bowed a little differently. `?gmod=0` takes
 * the grid away and leaves the frameless sheet. */
const GLASS_MOD = uniform( + ( __q.get( 'gmod' ) ?? 1.58 ) );
const GLASS_JOINT = uniform( + ( __q.get( 'gjoint' ) ?? 0.80 ) );
/* How much of the avenue is in the reflection. A pane on a street front
 * does not mirror the sky: it mirrors the sky ABOVE and the far side of the
 * road BELOW, and the line between them falls inside the floor, because the
 * reflected ray leaves at the same small angle the eye came in at. That is
 * what makes a glazed facade read as a chequer of pale and dark panes
 * instead of as one wash - each pane bows a shade differently and lands on
 * its own side of the line. `?gcity=0` leaves the sky alone. */
const GLASS_CITY = uniform( + ( __q.get( 'gcity' ) ?? 0.72 ) );
/* ?glass=0 is the old opening: a hole with nothing in it. */
const GLASS_AMOUNT = uniform( + ( __q.get( 'glass' ) ?? 1 ) );
/* every dial above is a uniform rather than a constant, so the whole pane
 * can be moved from the console over one boot - `tools/glasstune.cjs` */
window.__glass = { f0: GLASS_F0, f90: GLASS_F90, body: GLASS_BODY,
	green: GLASS_GREEN, env: GLASS_ENV, bow: GLASS_BOW, sun: GLASS_SUN,
	grime: GLASS_GRIME, amount: GLASS_AMOUNT,
	mod: GLASS_MOD, joint: GLASS_JOINT, city: GLASS_CITY,
	set: ( o ) => { for ( const k in o ) if ( window.__glass[ k ] )
		window.__glass[ k ].value = Array.isArray( o[ k ] )
			? new THREE.Vector3( ...o[ k ] ) : o[ k ];
	invalidate( 30 ); } };
let floorGlass = [ null, null ];

/* One slot's pane. Everything that says WHERE the glass is comes off that
 * slot's own x-ray uniforms, so the sheet appears exactly as the wall goes:
 * solid across the parting line as it travels, and over the rest of the
 * storey at whatever fraction of the wall has dissolved. Nothing here has
 * to be written per frame. */
function floorGlassMaterial( S ) {

	const m = new THREE.MeshBasicNodeMaterial();
	m.name = 'floor_glass';
	m.transparent = true;
	m.depthWrite = false;              // it is a sheet over rooms, not a wall
	m.side = THREE.DoubleSide;

	const P = positionWorld;
	const toEye = cameraPosition.sub( P );
	const V = toEye.div( length( toEye ) );
	/* Two sided, because a visitor can walk the camera behind the facade:
	 * turn the normal to face the eye or the reflection flips into the
	 * ground the moment they do. */
	const n0 = normalWorld;
	const nf = n0.mul( dot( n0, V ).lessThan( 0.0 ).select( float( - 1.0 ), float( 1.0 ) ) );
	const ndv = saturate( dot( nf, V ) );

	/* WHERE ALONG THE PANE a fragment is, in metres of the building's own
	 * frame. `cross( up, n )` is the pane's own horizontal axis, so this is
	 * one expression for both sheets - along the street for the front, into
	 * the plan for the gable - and one material can serve them both. */
	const T = normalize( cross( vec3( 0.0, 1.0, 0.0 ), nf ) );
	const along = dot( P.sub( xray.o ), T );
	// held off zero: ?gmod=0 asks for no grid, not for a divide by nothing
	const cell = along.div( GLASS_MOD.max( float( 0.05 ) ) );
	const ph = cell.fract();
	const id = cell.floor();

	/* A sealed unit is never flat: the gas in it is closed at the factory
	 * and the pane bows in or out by a millimetre or two with the weather.
	 * That is the whole of why a glazed facade never mirrors the sky as one
	 * clean sheet - the reflection STEPS at every joint, because the pane
	 * beside this one was closed on a different day. So the swell is two
	 * parts: a constant tilt per pane, which is what you actually see, and
	 * a slow metre-scale wander inside it. On the REFLECTED ray rather than
	 * on the normal - for a sheet this near a mirror the two are the same
	 * picture, and this way it is four sines. */
	const rnd = ( k ) => fract( sin( id.add( k ).mul( 12.9898 ) ).mul( 43758.5453 ) ).sub( 0.5 );
	const w1 = sin( P.y.mul( 1.7 ).add( along.mul( 0.61 ) ) ).mul( 0.45 ).add( rnd( 0.0 ).mul( 1.7 ) );
	const w2 = sin( P.y.mul( 0.93 ).sub( along.mul( 0.47 ) ).add( 1.7 ) ).mul( 0.45 )
		.add( rnd( 7.3 ).mul( 1.2 ) );
	const R = normalize( reflect( V.negate(), nf )
		.add( vec3( 0.0, 1.0, 0.0 ).mul( w1.mul( GLASS_BOW ) ) )
		.add( T.mul( w2.mul( GLASS_BOW.mul( 0.7 ) ) ) ) );

	/* The rain runs down a pane from the head and the dust that nothing
	 * washes off collects along its foot. One hash per column of the quad,
	 * which is what a run is, and a gradient at the sill. */
	const g = uv();
	const runs = fract( sin( g.x.mul( 311.7 ) ).mul( 43758.5453 ) );
	const run = smoothstep( 0.62, 1.0, runs ).mul( oneMinus( smoothstep( 0.30, 0.92, g.y ) ) );
	const foot = oneMinus( smoothstep( 0.0, 0.10, g.y ) );
	const grime = saturate( run.mul( 0.55 ).add( foot.mul( 0.9 ) ) ).mul( GLASS_GRIME );

	const sky = maps && maps.sky
		? texture( maps.sky, equirectUV( R ) ).rgb
		: vec3( 0.40, 0.42, 0.46 );
	/* ...and the avenue under it. Everything below the horizon is built on,
	 * and a wall lit from the side returns a third of what the sky does, so
	 * the mirrored city is the same haze at a low albedo rather than a
	 * colour of its own - which keeps it in the palette the rest of the
	 * frame is graded to, whatever the sky is doing. */
	const low = oneMinus( smoothstep( 0.02, 0.30, R.y ) ).mul( GLASS_CITY );
	const refl = sky.mul( mix( float( 1.0 ), float( 0.30 ), low ) )
		.mul( GLASS_ENV ).mul( oneMinus( grime.mul( 0.5 ) ) );
	/* The light sky carries no sun disc - it is the one that feeds the PMREM,
	 * and a second sun in there would light the whole street twice - so the
	 * glint the pane would catch off the real one is put back here. Two
	 * lobes: the disc, and the aureole around it that is what actually makes
	 * a facade flare. */
	const sd = saturate( dot( R, vec3( SUN_DIR.x, SUN_DIR.y, SUN_DIR.z ) ) );
	const glint = vec3( SUN_COLOR.r, SUN_COLOR.g, SUN_COLOR.b )
		.mul( pow( sd, 1800.0 ).add( pow( sd, 80.0 ).mul( 0.09 ) ) )
		.mul( GLASS_SUN ).mul( oneMinus( grime ) );

	const F = GLASS_F0.add( GLASS_F90.sub( GLASS_F0 ).mul( pow( oneMinus( ndv ), 5.0 ) ) );
	/* How much of the room the pane takes: what it mirrors, what its own
	 * substance holds back, and what the dirt on it stops. */
	const gA = saturate( F.add( GLASS_BODY ).add( grime.mul( 0.20 ) ) );
	/* ...and what it puts there instead. Blending is `C*A + room*(1-A)`, so
	 * every term is written as its CONTRIBUTION and divided back out by A at
	 * the end - which keeps the sky weighted by Fresnel and the glint purely
	 * additive, rather than all of it riding on one alpha. */
	const gC = refl.mul( F )
		.add( GLASS_GREEN.mul( GLASS_BODY ) )
		.add( vec3( 0.30, 0.29, 0.27 ).mul( grime.mul( 0.20 ) ) )
		.add( glint );

	/* The joint between two panes. It is what gives the sheet a scale - a
	 * module the eye can measure the floor against - and it is the line the
	 * stepped reflections break along, so the two work as one thing. Soft
	 * edged on purpose: at this distance the gasket is a pixel and a hard
	 * line crawls under the temporal filter. */
	const edge = ph.min( oneMinus( ph ) );
	const joint = oneMinus( smoothstep( 0.010, 0.032, edge ) )
		.mul( GLASS_JOINT ).mul( saturate( GLASS_MOD.mul( 1e3 ) ) );
	// dark anodised, and it takes a little of the sky like everything else
	const gasket = vec3( 0.035, 0.036, 0.040 ).add( refl.mul( 0.07 ) );

	const A = mix( gA, float( 0.94 ), joint );
	const C = mix( gC, gasket.mul( 0.94 ), joint ).div( A.max( float( 0.001 ) ) );

	/* Where the glass IS. `lo.z..hi.z` is the parting line the wall opens
	 * along, and over the rest of the storey `fade` is the fraction of the
	 * wall the stipple has already dropped - so the sheet arrives exactly as
	 * the wall leaves, and neither is ever seen through the other. */
	const band = atLeast( S.lo.z, P.y ).mul( atLeast( P.y, S.hi.z ) );
	const here = max( band, S.fade ).mul( S.amt );

	m.colorNode = C;
	m.opacityNode = A.mul( here ).mul( GLASS_AMOUNT );
	return m;

}

/* The two sheets - one per slot, each a street front and the gable round
 * the corner from it, which is the pair of boxes the storey opens along.
 * They are built once and carried to whichever storey the slot has taken;
 * only `position.y` ever changes. */
function buildFloorGlass() {
	const b = meta && meta.block && meta.block.floors;
	const f = meta && meta.flat;
	if ( ! b || ! f ) return;
	const o = new THREE.Vector3( ...f.origin );
	const ex = new THREE.Vector3( ...f.ex ).normalize();
	const ey = new THREE.Vector3( ...f.ey ).normalize();
	const up = new THREE.Vector3( 0, 1, 0 );
	const quat = new THREE.Quaternion().setFromRotationMatrix(
		new THREE.Matrix4().makeBasis( ex, up, ex.clone().cross( up ) ) );
	const gableQuat = new THREE.Quaternion().setFromRotationMatrix(
		new THREE.Matrix4().makeBasis( ey, up, ey.clone().cross( up ) ) );
	/* Exactly the opening, not the whole storey: the wall is only taken as
	 * far as the last flat (`row.end`), and a sheet of glass standing on
	 * black plaster past it would be the one thing that gave the trick
	 * away. The two run 0.10 m past the corner so they meet there. */
	const end = ( f.row ? f.row.end : b.len ) + 0.4;
	const depth = b.depth || 18;
	const hgt = b.h - 0.10;                        // the slab is not glazed
	for ( let i = 0; i < 2; i ++ ) {
		const mat = floorGlassMaterial( xray.slots[ i ] );
		const grp = new THREE.Group();
		grp.name = 'floor_glass_' + ( i ? 'b' : 'a' );
		const pane = ( geo, pos, q ) => {
			const mesh = new THREE.Mesh( geo, mat );
			mesh.position.copy( pos ).setY( 0 );
			mesh.quaternion.copy( q );
			mesh.renderOrder = 4;
			mesh.castShadow = mesh.receiveShadow = false;
			mesh.frustumCulled = false;            // so the warm frame draws it
			grp.add( mesh );
		};
		pane( new THREE.PlaneGeometry( end + 0.10, hgt ),
			o.clone().addScaledVector( ex, ( end - 0.10 ) * 0.5 ).addScaledVector( ey, - 0.08 ),
			quat );
		pane( new THREE.PlaneGeometry( depth + 0.10, hgt ),
			o.clone().addScaledVector( ex, - 0.08 )
				.addScaledVector( ey, ( depth - 0.10 ) * 0.5 ),
			gableQuat );
		grp.visible = false;           // until a storey takes it - floorPlace
		scene.add( grp );
		floorGlass[ i ] = grp;
	}
}

function hideFloorGlass() {
	for ( const g of floorGlass ) if ( g ) g.visible = false;
}

/* An unbuilt pipeline draws NOTHING in WebGPU, so the first storey to open
 * would open on an empty hole. The glass rides in the boot's warm frame
 * with the rest of the street - one quad whose alpha is zero, because no
 * slot is live - and goes away again the moment that frame is recorded.
 * This has to hang off the frame rather than off the end of the boot: the
 * page calls `setScene( 1 )` on its way to the warm, and that resets the
 * floor map, which puts the glass back down. */
function warmFloorGlass() {
	const was = floorGlass.map( g => g && g.visible );
	for ( const g of floorGlass ) if ( g ) g.visible = true;
	return () => floorGlass.forEach( ( g, i ) => { if ( g ) g.visible = was[ i ]; } );
}

const _fray = new THREE.Raycaster();
const _fndc = new THREE.Vector2();
let floorPointer = null, floorDirty = false;
/* which storey the pointer named while the flat was still warming, so the
 * page's floor tag is not re-announced on every frame of the wait */
let floorPreview = 0;

/* The storey under the pointer, or 0 - one ray against nine quads. The
 * click asks with its own coordinates rather than the hover's, so a tap -
 * which never moves a pointer across the canvas first - still names a
 * floor. */
function floorUnder( px = floorPointer ) {
	if ( ! px || ! floorMap ) return 0;
	const r = renderer.domElement.getBoundingClientRect();
	_fndc.set( ( px[ 0 ] - r.left ) / r.width * 2 - 1,
		- ( ( px[ 1 ] - r.top ) / r.height ) * 2 + 1 );
	_fray.setFromCamera( _fndc, camera );
	const hit = _fray.intersectObjects( floorMap.children, false )[ 0 ];
	return hit ? hit.object.userData.floor : 0;
}

/* The floor under the pointer. Only the bands are tested - nothing is asked
 * whether it stands in front of them, so a tree between the camera and the
 * facade still hovers the floor behind it, which is what you want, and the
 * whole thing is one ray against nine quads rather than against the merged
 * millions of the street. */
function floorTest() {
	// the real building's storeys: see `lvBandTest`
	if ( FLAT_GONE ) return lvBandTest();
	if ( FLAT_GONE || ! floorPointer || ! floorMap || sceneNo !== 1 || ! flyAllowed )
		return setHotFloor( 0 );
	const dom = renderer.domElement;
	/* The wall does not part until the flat can be drawn - a pipeline that
	 * has not been built yet draws NOTHING in WebGPU, so hovering mid-warm
	 * opens on a half furnished room. But never dead for long either: a tab
	 * that is throttled, or a machine that is slow, can take an age over the
	 * warm and a hover that does nothing reads as broken. So it arms on the
	 * COMPILES - not on the whole warm, whose last stretch only saves the
	 * first open its draw cost - or on a deadline, whichever lands first. */
	if ( ! floorArmed ) {
		if ( ! floorArming ) {
			floorArming = true;
			const arm = () => { floorArmed = true; floorDirty = true; invalidate(); };
			prepareScene2();
			compiledPromise().then( arm );
			/* The deadline is a backstop against a slow WARM, and it was
			 * written when the flat's GEOMETRY was in the scene from boot,
			 * so there was always something to open onto and the only thing
			 * missing could be a pipeline. Since the model was split the
			 * geometry is a download, and a deadline that fires before it
			 * lands parts the wall onto a storey with nothing in it - which
			 * reads as the page being broken, not as it still loading.
			 *
			 * So the clock starts when the flat is IN, not when the pointer
			 * arrives. Once the file has landed - and always, with
			 * `?glbsplit=0` - that is immediately, and the behaviour is the
			 * old one exactly. A flat that fails to load still arms on the
			 * deadline, because a hover that never answers is worse than
			 * one that opens on an empty room. */
			/* ...and it does not fire over pipelines that are still being
			 * BUILT. They are asked for through the async call now (see
			 * `pipesGather`), and an object whose pipeline has not landed is
			 * skipped rather than waited for - so arming in the middle of
			 * that would part the wall on a room the furniture then arrives
			 * in piece by piece. With the OS shader cache warm nothing is
			 * ever pending for more than a frame and this changes nothing;
			 * on a first visit it holds the wall until the flat is whole,
			 * while the cursor and the floor tag go on answering. Capped,
			 * for the same reason the deadline exists at all. */
			const t0 = performance.now();
			const late = () => ( pipesPending > 0 && performance.now() - t0 < FLOOR_ARM_CAP )
				? setTimeout( late, 120 ) : arm();
			const deadline = () => setTimeout( late, FLOOR_ARM_MS );
			loadFlat().then( deadline, deadline );
		}
		/* Not armed is not the same as not answering. The wall must not part
		 * on a room whose furniture has no pipeline yet, but the RAY is free
		 * and so is everything that is not the opening: the cursor turns and
		 * the page's floor tag names the flats on that storey straight away.
		 * Before this the whole hover was dead for as long as the warm took,
		 * which read as the page being broken. */
		const n = floorUnder();
		dom.style.cursor = n ? 'progress' : 'grab';
		if ( n !== floorPreview ) { floorPreview = n; announce( 'floor', { floor: n } ); }
		return;
	}
	floorPreview = 0;
	setHotFloor( floorUnder() );
	dom.style.cursor = floorHot ? 'pointer' : 'grab';
}

/* Which floor the pointer is over, 0 for none. The storey answers three
 * ways at once: its street wall is dropped by the x-ray box, the rooms that
 * stand behind it are switched on, and a sheet of the brand's amber is laid
 * over the opening, so the floor reads as glass rather than as a hole. */
/* Two storeys can be moving at once: the one the pointer has left is
 * shutting while the one it is on is already opening, in the same frames.
 * Each gets a slot - its own pair of x-ray boxes, its own room box, its own
 * dial and its own copy of the flat - because one flat cannot stand on two
 * floors. The second copy is `group.clone()`: three.js shares the geometry
 * and the materials, so it is a few nodes, not a second building, and it is
 * made the first time a visitor crosses from one floor to another. */
const floorSlots = [
	{ n: 0, open: 0, want: 0, box: null, rooms: null, flat: null },
	{ n: 0, open: 0, want: 0, box: null, rooms: null, flat: null },
];

function floorFlat( i ) {
	const slot = floorSlots[ i ];
	if ( slot.flat ) return slot.flat;
	if ( ! groups.flat ) return null;
	if ( i === 0 ) { slot.flat = groups.flat; return slot.flat; }
	const twin = groups.flat.clone( true );
	twin.name = 'group_flat_b';
	twin.visible = false;
	scene.add( twin );
	slot.flat = twin;
	return twin;
}

function setHotFloor( n ) {
	if ( n === floorHot || ! floorMap ) return;
	floorHot = n;
	// in the street the cursor is the only thing that says a storey is a
	// thing you can click, because there is no drag left to imply it
	embedCursor( false );
	const open = floorSlots.find( s => s.n && s.want > 0 );
	if ( open && open.n === n ) { announce( 'floor', { floor: n } ); invalidate(); return; }
	if ( open ) open.want = 0;                       // this one starts shutting
	if ( n ) {
		// ...and the other starts opening in the same breath
		const free = floorSlots.find( s => s !== open ) || floorSlots[ 0 ];
		floorPlace( free, n );
		free.want = 1;
	}
	announce( 'floor', { floor: n } );
	invalidate();
}

/* Where a slot's opening is: the boxes that storey wants when it is fully
 * open, the room box the shader lifts, and this slot's flat carried to it.
 * How MUCH of it is open is the slot's own dial, which `floorStep` holds. */
function floorPlace( slot, n ) {
	if ( ! meta || ! meta.block || ! meta.block.floors ) return;
	const b = meta.block.floors, row = meta.flat.row;
	const end = row ? row.end : b.len;
	const yEnd = meta.flat.size ? meta.flat.size[ 1 ] : 8.4;
	const zLo = b.base + ( n - 1 ) * b.h + 0.06, zHi = b.base + n * b.h - 0.04;
	slot.n = n;
	/* Everything of the street front on that storey: the wall, the windows
	 * in it, and the balconies behind it, which is why the box runs back
	 * past the loggia's own back wall at 2.07 rather than stopping at the
	 * wall's depth. The rooms start beyond it and are int_* materials
	 * anyway, so they stand. Across, it stops at the last flat - open the
	 * wall past them and the storey has nothing behind it but sky. The
	 * second box is the end wall round the corner, for its whole depth. */
	slot.box = {
		lo: [ - 0.5, - 1.5, zLo ], hi: [ end + 0.4, 2.30, zHi ],
		glo: [ - 1.6, - 0.6, zLo ], ghi: [ 0.80, ( b.depth || 18 ) + 0.4, zHi ],
	};
	slot.rooms = { lo: [ - 0.5, - 0.5, zLo ], hi: [ end + 0.4, yEnd + 0.3, zHi ] };
	if ( xray ) {
		xray.o.value.set( ...meta.flat.origin );
		xray.ex.value.set( ...meta.flat.ex ).normalize();
		xray.ey.value.set( ...meta.flat.ey ).normalize();
		// the flat's own lining of that wall is only a finger deep: any
		// further in and the partitions go with it
		xray.skin.value = 0.60;
	}
	/* What stands in the opening is THE flat - the four units built and
	 * furnished for the show flat, carried to this storey. Its own facade,
	 * gable and loggia shells are shell materials, so the x-ray drops them
	 * with the building's and only the rooms are left. */
	const flat = floorFlat( floorSlots.indexOf( slot ) );
	if ( flat ) {
		flat.position.y = ( n - b.n ) * b.h;
		flat.visible = true;
	}
	// ...and the sheet of glass that stands where its wall did
	const pane = floorGlass[ floorSlots.indexOf( slot ) ];
	if ( pane ) { pane.position.y = ( zLo + zHi ) * 0.5; pane.visible = true; }
	floorApply();                     // the opening follows at once
}

/* The wall does not blink away: it parts along a horizontal line across the
 * whole floor and opens upward and downward from the middle of the storey in
 * FLOOR_OPEN seconds, on an ease in, and shuts the same way. Both slots run
 * at once, so leaving one floor for another is one movement, not a wait.
 * This runs off the frame loop rather than the tween list, because the rail
 * pauses itself while a tween is in flight. */
/* Returns whether anything actually moved, which the frame loop needs to
 * know: see the density ladder in `frame()`. */
function floorStep( dt ) {
	if ( ! xray ) return false;
	let moved = false;
	for ( const slot of floorSlots ) {
		if ( slot.open === slot.want ) continue;
		const d = dt / FLOOR_OPEN;
		slot.open = slot.want > slot.open
			? Math.min( slot.want, slot.open + d ) : Math.max( slot.want, slot.open - d );
		moved = true;
		if ( slot.open === 0 ) {                     // shut: give the flat back
			slot.n = 0;
			if ( slot.flat ) { slot.flat.visible = false; slot.flat.position.y = 0; }
			const pane = floorGlass[ floorSlots.indexOf( slot ) ];
			if ( pane ) pane.visible = false;
		}
	}
	if ( ! moved ) return false;
	/* Turn the dissolve's pattern - a golden-ratio step, so no two frames of
	 * the open land on the same phase and the stipple averages to a fade
	 * under the temporal filter rather than standing there as grain. */
	xray.seed.value = ( xray.seed.value + 0.6180339887 ) % 1.0;
	floorApply();
	invalidate( SETTLE );
	return true;                     // ...and it counts as motion: see frame()
}

/* Everything shut, at once and without an animation: the tour is about to
 * take the flat, and a slot easing closed behind it would leave the twin
 * standing in the street for half a second. */
function floorReset() {
	floorHot = 0;
	for ( const slot of floorSlots ) {
		slot.n = 0; slot.open = 0; slot.want = 0;
		if ( slot.flat ) { slot.flat.visible = false; slot.flat.position.y = 0; }
	}
	hideFloorGlass();
	floorApply();
}

/* Write both dials out: the boxes, the glass and the glow. Called by the
 * step above and by `floorPlace`, because a slot that is already wide open
 * would never be written by the step. */
function floorApply() {
	if ( ! xray ) return;
	for ( let i = 0; i < floorSlots.length; i ++ ) {
		const slot = floorSlots[ i ], S = xray.slots[ i ];
		const e = slot.open * slot.open;             // ease in
		S.amt.value = slot.open > 0 ? 1 : 0;
		/* The dissolve, over the whole storey rather than the band. Linear
		 * and a little faster than the open, because the ease is already in
		 * the box below and squaring the fade as well left the first half of
		 * the movement looking like nothing was happening. Clamped, so at
		 * rest it is exactly 0 or exactly 1 and the cut is binary again - a
		 * parked frame is never stippled, and the still render is what it
		 * always was. */
		S.fade.value = Math.min( 1, slot.open * FLOOR_FADE );
		S.lift.value = FLOOR_GLOW * e;
		if ( ! slot.box ) continue;
		const B = slot.box;
		// the cut is a horizontal line across the whole floor that opens
		// upward and downward from the middle of the storey - a shutter,
		// not a pair of curtains
		const zmid = ( B.lo[ 2 ] + B.hi[ 2 ] ) * 0.5;
		const zLo = zmid + ( B.lo[ 2 ] - zmid ) * e;
		const zHi = zmid + ( B.hi[ 2 ] - zmid ) * e;
		S.lo.value.set( B.lo[ 0 ], B.lo[ 1 ], zLo );
		S.hi.value.set( B.hi[ 0 ], B.hi[ 1 ], zHi );
		S.glo.value.set( B.glo[ 0 ], B.glo[ 1 ], zLo );
		S.ghi.value.set( B.ghi[ 0 ], B.ghi[ 1 ], zHi );
		if ( slot.rooms ) {
			S.rlo.value.set( ...slot.rooms.lo );
			S.rhi.value.set( ...slot.rooms.hi );
		}
	}
	if ( floorMap ) for ( const m of floorMap.children ) {
		const slot = floorSlots.find( s => s.n === m.userData.floor );
		m.material.opacity = slot ? FLOOR_LIT * slot.open * slot.open : 0;
		/* A band at opacity 0 is invisible but not free: it is a facade-sized
		 * blended quad, two-sided and never frustum culled, and eighteen of
		 * them were rasterised into every frame of the street for the sake of
		 * the one that might light. Hit testing does not care - three.js
		 * raycasts invisible objects just the same - so they are only in the
		 * frame when they are lit. */
		m.visible = m.material.opacity > 0.002;
	}
}

/* ===================================================== the real levels
 * Everything the page used to do with the one invented show flat, done
 * with the architect's building: driven by scene_meta.json (the frame, the
 * levels, the facades) and plan_meta.json (per level the flats, their
 * polygons, label points and rooms), with not one plan number typed here.
 * levels.js knows the data and the drawing; this is the state machine.
 *
 *   street    the storey under the pointer lights across the WHOLE L - one
 *             level is one floor plate, the two blocks share the corridor -
 *             and the page names it ("Floor 5 of 9 · 23 flats"). A click
 *             opens that level.
 *   level     ('plan', scene 2) everything of both blocks over the level's
 *             section height is taken off by `towerPlane`, the level's own
 *             interior is cut at the same height by `lvPlane` and capped in
 *             ink, and the camera comes over the whole plate. The storey is
 *             DRAWN: ink walls, amber floors, one badge per flat with its
 *             real number and area; the flat under the pointer comes back
 *             as modelled.
 *   flat      a click on one, or the page's "See it in 3D", or #flat-37:
 *             the camera comes down onto it and its rooms carry dots.
 *   room      a dot puts the camera in the room at eye height, the clip
 *             lifted so the walls and ceiling are whole. Walking is the
 *             walk module's: see `LVL.hooks`.
 *
 * THE GATE. An interior is a download (web/interior/<LEVEL>.glb) and its
 * pipelines are a compile, and NOTHING of a level is put on screen before
 * both are done: `lvWith` is the one way in, and `P.state === 'in'` means
 * "the geometry is HERE and its pipelines are built", never "it has been
 * asked for" - the difference is the whole of the bug the split shipped
 * (memory: web-page-performance). The hover only lights a band on the
 * facade, which needs nothing loaded; the click waits on the gate with the
 * cursor saying so, and a hover that dwells has usually paid it already.
 * -------------------------------------------------------------------- */
/* The plan's section height over a level's floor, in metres: the walls are
 * cut here, which is above every sill (0.90) and below every head (2.10 and
 * 2.40), so a door reads as a gap and a window as a thinner wall. */
const LV_CUT = + ( __q.get( 'cut' ) ?? 1.45 );
/* How many levels are kept parsed at once: the one that is open and the one
 * it was left for. Anything further back is disposed and fetched again if a
 * visitor comes back to it - it is ~90 KB on the wire. */
const LV_RESIDENT = 2;
/* The lit storey's amber, at full, and how long it takes to light. */
const LV_BAND = + ( __q.get( 'band' ) ?? 0.36 );
const LV_BAND_OPEN = 0.30;
/* How long the pointer has to rest on one storey before that level is
 * fetched and compiled in the background - long enough that sweeping the
 * pointer up the facade does not fetch nine levels, short enough that the
 * level is usually in before the click. */
const LV_DWELL = 260;
/* The eye's field of view standing in a room. */
const LV_ROOM_FOV = 62;
/* MEASUREMENT ONLY: `?lvgate=0` takes the gate away - a click opens the
 * level as soon as the plan's numbers are in, whether its interior has
 * arrived or not. It exists so tools/flatwindow.cjs can be shown to FAIL
 * against the bug it guards; nothing else may use it. */
const LV_GATE = __q.get( 'lvgate' ) !== '0';

let frameP = null;                                  // plan metres <-> world
const lvPlane = new THREE.Plane( new THREE.Vector3( 0, - 1, 0 ), 1e4 );
let lvRoot = null;                                  // every resident interior, clipped
const lvParts = new Map();                          // 'L05' | 'cores' -> part
const lvMats = new Map();                           // the interior's own material copies
let lvCapMat = null;
let lvPM = null;                                    // plan_meta.json, once it is in
let lvLite = null;                                  // rooms_lite.json, once it is in
let lvOpen = null;          // the level scene 2 is open on
let lvFocusK = 0;           // the open flat's place in its level, 0 for none
let lvHotK = 0;             // ...and the one under the pointer
let lvRooms = [];           // the open flat's rooms (levels.js `roomsOf`)
let lvAsk = 0;              // only the latest open request acts
let lvWaiting = null;       // the level a click is waiting on, for the cursor
let lvWarm = Promise.resolve();   // one part's pipelines at a time
const lvWarmed = new Set();       // ...and the materials already compiled
const lvRev = new Float32Array( LVL.MAX_UNITS ), lvRevT = new Float32Array( LVL.MAX_UNITS );
let lvAmt = 0, lvDim = 0, lvInside = false;

const lvLevel = ( id ) => ( id && LVL.levelById( id ) ) || null;
const lvMetaLevel = ( id ) => ( ( meta && meta.levels ) || [] ).find( l => l.id === id ) || null;
/* The old scene numbered STOREYS, the podium terrace being 2's floor; the
 * real ids keep that count: storey n is `L0n`. Only the legacy `setScene`
 * and `LP.floor` still speak storeys. */
const lvStorey = ( id ) => { const m = /^L(\d\d)$/.exec( id || '' ); return m ? + m[ 1 ] : 0; };
const lvOfStorey = ( n ) => 'L' + String( n | 0 ).padStart( 2, '0' );
const lvUnit = ( k ) => { const L = lvLevel( lvOpen ); return ( L && k > 0 && L.units[ k - 1 ] ) || null; };

/* The interior's own copy of a material, patched to be drawn. Copies, so
 * the floor view's drawing can never reach the street: the lift cars are
 * `metal_dark`, which the street's poles are made of too. A copy shares the
 * whole node graph, so it IS the same surface until the drawing turns. */
function lvMat( name ) {
	if ( lvMats.has( name ) ) return lvMats.get( name );
	const base = sceneMaterials && sceneMaterials[ name ];
	let m = null;
	if ( base ) {
		m = base.clone();
		m.name = name;
		if ( PLAN2D ) LVL.patchDrawing( m, { ink: PLAN_INK, amber: PLAN_AMBER, lit: PLAN_LIT, gain: PLAN_GAIN } );
	}
	lvMats.set( name, m );
	return m;
}
/* The section cap's ink: unlit, so it is the same black whatever the sun is
 * doing to the roof around it, and it stands back with the rest of the
 * storey while one flat is open. */
function lvCapMaterial() {
	if ( lvCapMat ) return lvCapMat;
	const m = new THREE.MeshBasicNodeMaterial();
	m.name = 'level_cap';
	m.colorNode = PLAN_INK.mul( LVL.LVU.dim.oneMinus() );
	lvCapMat = m;
	return m;
}

/* The interior's floors carry the scanned parquet and tiles. A map that has
 * not landed is a 1x1 default under the same pipeline, so this is a
 * download and never a reason to wait. */
let lvMapsAsked = false;
function lvMaps() {
	if ( lvMapsAsked || ! maps ) return;
	lvMapsAsked = true;
	for ( const [ k, t ] of Object.entries( maps ) )
		if ( /^(parquet|btile|bfloor|planks)/.test( k ) && t && t.userData && t.userData.file ) fillMap( t );
}

const PREWARM_BOOT = __q.get( 'prewarm' ) === 'boot';
let lvPrewarmed = null;
function lvPrewarm() {
	if ( lvPrewarmed ) return lvPrewarmed;
	lvFurnPrefetch( 'L06' );
	lvPrewarmed = Promise.all( [ lvPart( 'L06' ), lvPart( 'cores' ) ] )
		.then( ( [ P ] ) => lvFurn( P ) ).catch( () => null );
	return lvPrewarmed;
}
/* One part: fetched, parsed through the street's own loader (Draco), welded
 * by levels.js into one mesh per material with each vertex's flat baked in,
 * capped, put in the scene hidden, and compiled through the gate. Resolves
 * once ALL of that is done - the promise is the gate. */
function lvPart( name ) {
	let P = lvParts.get( name );
	if ( P ) { P.usedAt = performance.now(); return P.ready; }
	P = { name, state: 'loading', group: null, cap: null, doors: [], tris: 0, usedAt: performance.now() };
	lvParts.set( name, P );
	if ( ! LV_ORDER ) lvMaps();
	P.ready = ( async () => {
		const t0 = performance.now();
		const bufP = LVL.fetchPart( name );
		if ( LV_ORDER ) bufP.then( lvMaps, () => {} );
		const [ buf, pm ] = await Promise.all( [ bufP, LVL.planMeta() ] );
		lvPM = pm;
		const tGot = performance.now();
		const level = name === 'cores' ? null : LVL.levelById( name );
		const gltf = await new Promise( ( res, rej ) => glbLoader.parse( buf, './', res, rej ) );
		const holder = new THREE.Group();
		holder.matrixAutoUpdate = false;
		holder.matrix.copy( frameP.matrix );
		holder.add( gltf.scene );
		const { meshes, doors, tris, lift } = LVL.weldPart( holder, level, lvMat,
			( miss ) => console.warn( 'unmapped materials in interior/' + name + ':', miss ) );
		/* Leaves, cars and landing doors: welded while at rest, hung on
		 * their hinges / in their shafts by the walk (levels.js makeMovers). */
		const g0 = new THREE.Group();
		gltf.scene.traverse( ( o ) => { if ( o.geometry ) o.geometry.dispose(); } );
		const g = g0;
		g.name = 'level_' + name;
		g.visible = false;
		for ( const m of meshes ) { m.frustumCulled = false; g.add( m ); }
		P.movers = LVL.makeMovers( g, doors );
		// the lifts' own doors, displays and call lamps (`liftKit`)
		if ( name === 'cores' ) P.lifts = liftKit( g, lift, pm );
		if ( level ) {
			/* A hair UNDER the cut, inside the clipped group: the walls are
			 * cut at exactly LV_CUT, so the cap fills each hollow wall head
			 * from just below its rim, and nothing ever stands over it. */
			const cap = new THREE.Mesh( LVL.capGeometry( level, frameP, level.z + LV_CUT - 0.004 ),
				lvCapMaterial() );
			cap.name = 'level_cap_' + name;
			cap.castShadow = false;
			cap.receiveShadow = false;
			cap.frustumCulled = false;
			g.add( cap );
			P.cap = cap;
		}
		lvRoot.add( g );
		Object.assign( P, { group: g, doors, tris, level } );
		const tBuilt = performance.now();
		await lvCompile( P );
		P.state = 'in';
		console.info( 'interior ' + name + ': ' + Math.round( tGot - t0 ) + ' ms to fetch, '
			+ Math.round( tBuilt - tGot ) + ' ms to parse and weld, '
			+ Math.round( performance.now() - tBuilt ) + ' ms to compile; '
			+ meshes.length + ' meshes, ' + Math.round( tris ) + ' triangles, '
			+ doors.length + ' moving parts stashed' );
		lvEvict();
		return P;
	} )();
	P.ready.catch( ( e ) => {
		console.warn( 'interior ' + name + ' did not load:', e );
		if ( lvParts.get( name ) === P ) lvParts.delete( name );
	} );
	return P.ready;
}

/* Through the existing gate: `compileInto` holds the frame loop off while a
 * pass compiles (a compile borrows the renderer), and parts queue behind one
 * another here so no two compiles ever overlap. The WHOLE clipped root is
 * what is compiled, not the meshes: a compile walks from the object it is
 * given, and only from the ClippingGroup down does an object know it is
 * clipped - compiled on their own the meshes would build the pipelines of an
 * UNclipped draw, and the real one would compile again in the frame. The
 * other resident levels are hidden, so only this one is walked. The
 * materials are shared by every level, so from the second level on there is
 * usually nothing left to build. */
/* ON A WALK a level's first arrival is not compiled through that gate. A
 * held loop is a frozen picture - 0.5-0.7 s for the cores and L00 on the
 * walk up to a street door (measured), the body standing still in it - and
 * on a walk the level can simply be put on screen to build: with
 * `pipesGather` on, three asks for its pipelines through the async call and
 * draws nothing of it until they stand (`Pipelines.isReady`), so the frames
 * go on and the level turns up a moment later where it belongs. Its section
 * cap (an ink slab at the floor view's cut) is kept out of it, and the
 * level is hidden again once built, for the walk's own gate (`bwReady`) to
 * show. `?bwasync=0` keeps the held compile, for an A/B. */
const BW_ASYNC = __q.get( 'bwasync' ) !== '0';
function lvWarmWalk( P, show, hide, mats, warmed ) {
	const job = lvWarm.then( async () => {
		const key = warmed === lvWarmed ? ( m ) => m : ( m ) => m.uuid;
		if ( [ ...mats ].every( m => warmed.has( key( m ) ) ) ) return;
		pipesGather();
		P.warming = true;
		show();
		shadowDirty();
		const r0 = __perf.rendered || 0;
		// two drawn frames: the beauty pass and the pre-pass both ask
		for ( let i = 0; i < 240 && ( __perf.rendered || 0 ) < r0 + 2; i ++ ) { invalidate( 2 ); await nextFrame(); }
		try { await pipesSettled(); } finally { P.warming = false; hide(); }
		shadowDirty();
		invalidate( 2 );
		for ( const m of mats ) warmed.add( key( m ) );
	} );
	lvWarm = job.catch( () => {} );
	return job;
}
function lvCompile( P ) {
	if ( bwOn && BW_ASYNC && PIPES ) {
		const mats = new Set( P.group.children.filter( o => o.isMesh && o !== P.cap ).map( o => o.material ) );
		let capWas = false;
		return lvWarmWalk( P, () => { if ( P.cap ) { capWas = P.cap.visible; P.cap.visible = false; } P.group.visible = true; },
			() => { if ( P.state !== 'in' ) P.group.visible = false; if ( P.cap ) P.cap.visible = capWas; }, mats, lvWarmed );
	}
	const job = lvWarm.then( async () => {
		const mats = new Set( P.group.children.filter( o => o.isMesh ).map( o => o.material ) );
		if ( [ ...mats ].every( m => lvWarmed.has( m ) ) ) return;
		await compileInto( prePass, [ lvRoot ], P.group );
		await compileInto( scenePass, [ lvRoot ], P.group );
		for ( const m of mats ) lvWarmed.add( m );
	} );
	lvWarm = job.catch( () => {} );
	return job;
}

/* At most LV_RESIDENT levels parsed: the least recently wanted goes first,
 * and never the one on screen. The cores stay - they are every level's. */
function lvEvict() {
	const lv = [ ...lvParts.values() ].filter( P => P.name !== 'cores' && P.state === 'in' );
	lv.sort( ( a, b ) => a.usedAt - b.usedAt );
	/* Walking, what the body needs now and the storeys either side of it
	 * are kept: a visitor turning back down a stair finds the level they
	 * have just left still here. */
	const keep = new Set( bwOn && bwS ? bwS.needLevels : [] );
	if ( bwOn && bwS && /^L\d\d$/.test( bwS.level ) ) for ( const d of [ - 1, 1 ] ) keep.add( lvOfStorey( lvStorey( bwS.level ) + d ) );
	while ( lv.length > ( bwOn ? BW_RESIDENT : LV_RESIDENT ) ) {
		const i = lv.findIndex( P => P.name !== lvOpen && ! P.group.visible && ! keep.has( P.name ) );
		if ( i < 0 ) break;
		const P = lv.splice( i, 1 )[ 0 ];
		lvParts.delete( P.name );
		P.state = 'gone';
		P.group.removeFromParent();
		/* three's render objects - and the node builder state each holds,
		 * a quarter of a gigabyte a level - are let go on the OBJECT's
		 * dispose (or the material's, which every level shares); disposing a
		 * geometry does not do it. */
		P.group.traverse( ( o ) => { if ( o.isMesh ) o.dispatchEvent( { type: 'dispose' } ); if ( o.geometry ) o.geometry.dispose(); } );
		if ( P.movers ) P.movers.dispose(); else for ( const d of P.doors ) d.geo.dispose();
		if ( P.furn ) P.furn.dispose();
	}
}

/* The one way onto a level: the part, the cores and the room facts, then
 * `then` - and only for the LATEST ask, so a visitor who clicks the fifth
 * storey and then the eighth while the fifth is still downloading ends up
 * on the eighth, once. */
function lvWith( id, then ) {
	const ask = ++ lvAsk;
	lvWaiting = id;
	embedCursor( false );
	lvFurnPrefetch( id );
	if ( ! LV_GATE ) {
		lvPart( id ).catch( () => {} ); lvPart( 'cores' ).catch( () => {} );
		return LVL.planMeta().then( ( pm ) => { lvPM = pm; lvWaiting = null; then(); return true; } );
	}
	return Promise.all( [ lvPart( id ), lvPart( 'cores' ),
		LVL.roomsLite().then( ( r ) => { lvLite = r; } ) ] ).then( () => {
		if ( ask !== lvAsk ) return false;
		lvWaiting = null;
		embedCursor( false );
		then();
		return true;
	}, ( e ) => {
		console.warn( 'level ' + id + ' could not be opened:', e );
		if ( ask === lvAsk ) { lvWaiting = null; embedCursor( false ); }
		return false;
	} );
}

/* Show or hide one level's interior and the cores with it. */
function lvShow( id, on ) {
	const P = lvParts.get( id );
	if ( P && P.group && P.group.visible !== on ) {
		P.group.visible = on;
		P.usedAt = performance.now();
		LVL.hooks.fire( on ? 'onLevelShown' : 'onLevelHidden', id, P.group );
	}
	const C = lvParts.get( 'cores' );
	if ( C && C.group ) C.group.visible = on || [ ...lvParts.values() ]
		.some( Q => Q !== P && Q.name !== 'cores' && Q.group && Q.group.visible );
	shadowDirty();
	invalidate();
}

/* ------------------------------------------------- the street's storeys */
let lvPick = null;                       // invisible quads the pointer is tested against
const lvSlots = [ { level: null, open: 0, want: 0, grp: null, mat: null },
	{ level: null, open: 0, want: 0, grp: null, mat: null } ];
let lvHotLevel = null, lvHoverAt = 0, lvFetched = null;

function lvBuildBands() {
	if ( ! frameP || ! meta || ! meta.facades ) return;
	const up = new THREE.Vector3( 0, 1, 0 );
	/* One face line of the L as a quad, 8 cm proud of it, from y0 up h. */
	const quad = ( f, y0, h ) => {
		const a = frameP.world( f.a[ 0 ] + f.out[ 0 ] * 0.08, f.a[ 1 ] + f.out[ 1 ] * 0.08, 0 );
		const b = frameP.world( f.b[ 0 ] + f.out[ 0 ] * 0.08, f.b[ 1 ] + f.out[ 1 ] * 0.08, 0 );
		const len = a.distanceTo( b );
		const dir = b.clone().sub( a ).normalize();
		const g = new THREE.PlaneGeometry( len, h );
		g.applyMatrix4( new THREE.Matrix4().makeBasis( dir, up, new THREE.Vector3().crossVectors( dir, up ) )
			.setPosition( a.clone().add( b ).multiplyScalar( 0.5 ).setY( y0 + h * 0.5 ) ) );
		return g;
	};
	const pickMat = new THREE.MeshBasicMaterial( { side: THREE.DoubleSide } );
	lvPick = new THREE.Group();
	lvPick.name = 'level_pick';
	for ( const q of LVL.bandQuads( meta ) ) {
		const m = new THREE.Mesh( quad( q, q.z, q.h ), pickMat );
		m.visible = false;                 // hit tested, never drawn
		m.userData.level = q.level;
		lvPick.add( m );
	}
	scene.add( lvPick );
	/* What lights: per slot, every face line at a unit height, carried to
	 * the level by its own position and scale. One material a slot - the
	 * same two-slot pattern the old storey used, so the storey being left
	 * fades out while the next one comes up, in the same frames. */
	const one = BufferGeometryUtils.mergeGeometries( meta.facades.map( f => quad( f, 0, 1 ) ) );
	for ( const s of lvSlots ) {
		s.mat = new THREE.MeshBasicNodeMaterial( { color: FLOOR_AMBER, transparent: true,
			opacity: 0, depthWrite: false, side: THREE.DoubleSide } );
		s.mat.name = 'level_band';
		const mesh = new THREE.Mesh( one, s.mat );
		mesh.renderOrder = 3;
		mesh.frustumCulled = false;
		mesh.castShadow = mesh.receiveShadow = false;
		s.grp = new THREE.Group();
		s.grp.name = 'level_band';
		s.grp.add( mesh );
		s.grp.visible = false;
		scene.add( s.grp );
	}
}

/* The bands' pipelines ride in the boot's warm frame, at zero opacity, so
 * the first storey to light is not the first draw of its material. */
function lvWarmBands() {
	const was = lvSlots.map( s => s.grp && s.grp.visible );
	for ( const s of lvSlots ) if ( s.grp ) s.grp.visible = true;
	return () => lvSlots.forEach( ( s, i ) => { if ( s.grp ) s.grp.visible = was[ i ]; } );
}

function lvBandUnder( px = floorPointer ) {
	if ( ! px || ! lvPick ) return null;
	const r = renderer.domElement.getBoundingClientRect();
	_fndc.set( ( px[ 0 ] - r.left ) / r.width * 2 - 1, - ( ( px[ 1 ] - r.top ) / r.height ) * 2 + 1 );
	_fray.setFromCamera( _fndc, camera );
	const hit = _fray.intersectObjects( lvPick.children, false )[ 0 ];
	return hit ? hit.object.userData.level : null;
}

/* The storey under the pointer, on the street. Nothing has to be loaded for
 * this - it is a band of light on the facade - so it answers from the first
 * frame; the level itself is fetched once the pointer has rested on it. */
function lvBandTest() {
	if ( ! floorPointer || ! lvPick || sceneNo !== 1 || ! flyAllowed || tweens.length ) {
		bwHotSet( null );
		return lvSetHot( null );
	}
	// a street door under the pointer is a way in, and no storey is lit
	const door = bwDoorUnder( floorPointer );
	bwHotSet( door );
	lvSetHot( door ? null : lvBandUnder() );
}

function lvFloorDetail( id ) {
	const ml = lvMetaLevel( id ), L = lvLevel( id );
	return { level: id || null, floor: ml && ml.res ? ml.res : 0,
		flats: L ? L.units.filter( u => ! u.office ).length : undefined,
		offices: L ? L.units.filter( u => u.office ).length : undefined };
}

function lvSetHot( id ) {
	if ( id === lvHotLevel ) return;
	if ( id ) lvPrewarm();                 // intent: the interiors start loading
	lvHotLevel = id;
	lvHoverAt = performance.now();
	embedCursor( false );
	const open = lvSlots.find( s => s.level && s.want > 0 );
	if ( ! ( open && open.level === id ) ) {
		if ( open ) open.want = 0;                      // this one starts going out
		const L = lvMetaLevel( id );
		if ( L ) {
			const free = lvSlots.find( s => s !== open ) || lvSlots[ 0 ];
			free.level = id;
			free.grp.position.y = L.z;
			free.grp.scale.y = L.h;
			free.grp.visible = true;
			free.want = 1;
		}
	}
	announce( 'floor', lvFloorDetail( id ) );
	invalidate();
}

/* The two dials, off the frame loop rather than the tween list (a tween in
 * flight pauses the rail). Returns whether anything moved - see `frame`. */
function lvBandStep( dt ) {
	let moved = false;
	for ( const s of lvSlots ) {
		if ( s.open === s.want ) continue;
		const d = dt / LV_BAND_OPEN;
		s.open = s.want > s.open ? Math.min( s.want, s.open + d ) : Math.max( s.want, s.open - d );
		s.mat.opacity = LV_BAND * s.open * s.open;
		if ( s.open === 0 ) { s.grp.visible = false; s.level = null; }
		moved = true;
	}
	/* A pointer that has rested on a storey is a visitor about to click it:
	 * the level is fetched and compiled now, behind the light. */
	if ( lvHotLevel && lvHotLevel !== lvFetched && performance.now() - lvHoverAt > LV_DWELL ) {
		lvFetched = lvHotLevel;
		lvFurnPrefetch( lvHotLevel );
		lvPart( lvHotLevel ).then( ( P ) => lvFurn( P ) ).catch( () => {} );
		lvPart( 'cores' ).catch( () => {} );
	}
	if ( moved ) invalidate( SETTLE );
	return moved;
}

function lvBandsReset() {
	lvHotLevel = null;
	for ( const s of lvSlots ) {
		s.open = s.want = 0; s.level = null;
		if ( s.grp ) s.grp.visible = false;
		if ( s.mat ) s.mat.opacity = 0;
	}
}

/* ------------------------------------------------- opening a level */
function lvOpenLevel( id, flatN = null ) {
	if ( bwOn ) bwExit( 'none' );
	const ml = lvMetaLevel( id );
	if ( ! frameP || ! ml || ! ( ml.h > 0 ) || ml.kind === 'parking' ) return false;
	lvWith( id, () => lvEnter( id, flatN ) );
	return true;
}

/* A flat by its own number ('37', '47-a'). Its level comes from plan_meta,
 * which may still be on its way - the answer is true as long as the number
 * can be a flat at all, and the page is told through `lp:planfocus` when it
 * is actually open. */
function lvOpenFlat( n ) {
	if ( n == null || ! frameP ) return false;
	if ( LVL.planReady() && ! LVL.flatByN( n ) ) return false;
	LVL.planMeta().then( ( pm ) => {
		lvPM = pm;
		const u = LVL.flatByN( n );
		if ( u ) lvOpenLevel( u.level, u.n );
	}, () => {} );
	return true;
}

/* Which flat the page's "tour" should open when nobody has chosen one: the
 * one open now, or else the top floor's largest flat with a loggia -
 * read off the plan, so it is a real flat whatever the build renumbers. */
function lvShowFlat() {
	const u = lvUnit( lvFocusK );
	if ( u && ! u.office ) return u.n;
	if ( ! lvPM ) return null;
	const top = [ ...( lvPM.levels || [] ) ].reverse().find( L => ( L.flats || [] ).length );
	if ( ! top ) return null;
	const pick = [ ...top.flats ].sort( ( a, b ) =>
		( ( b.loggias || [] ).length ? 1 : 0 ) - ( ( a.loggias || [] ).length ? 1 : 0 )
		|| ( ( b.area && b.area.total ) || 0 ) - ( ( a.area && a.area.total ) || 0 ) )[ 0 ];
	return pick ? pick.n : null;
}

function lvEnter( id, flatN = null ) {
	const L = lvLevel( id ), P = lvParts.get( id );
	if ( ! L || ( LV_GATE && ( ! P || P.state !== 'in' ) ) ) return;
	if ( sceneNo === 2 && lvOpen === id && ! sceneSettling ) {
		if ( flatN != null ) lvFocus( L.units.find( u => ! u.office && String( u.n ) === String( flatN ) ) || null );
		return;
	}
	const fromStreet = sceneNo !== 2;
	const was = lvOpen;
	sceneSettling = true;
	try {
		lvBandsReset();
		tweens.length = 0;
		sceneNo = 2;
		scene2View = 'plan';
		planStepReset();
		if ( fromStreet ) setPlanUp();
		lvOpen = id;
		lvFocusK = 0; lvHotK = 0; lvRooms = [];
		lvRev.fill( 0 ); lvRevT.fill( 0 );
		for ( let k = 0; k < LVL.MAX_UNITS; k ++ ) LVL.LVU.rev.array[ k ] = 0;
		lvInsideSet( false );
		if ( was && was !== id ) lvShow( was, false );
		lvShow( id, true );
		if ( P && P.cap ) P.cap.visible = true;     // a plan is capped (a walk may have left it off)
		lvFurn( P );
		if ( P && P.furn ) lvFurnSync( P );
		lvPlane.constant = L.z + LV_CUT;
		planHold = fromStreet ? PLAN_HOLD : 0;
		const u = flatN != null ? L.units.find( x => ! x.office && String( x.n ) === String( flatN ) ) : null;
		if ( u ) { lvFocusK = lvHotK = u.k; lvRooms = LVL.roomsOf( u, lvLite ); }
		announce( 'scene', { scene: 2, view: 'plan', level: id, floor: lvStorey( id ) } );
		$( 's_1' ).setAttribute( 'aria-pressed', 'false' );
		$( 's_2' ).setAttribute( 'aria-pressed', 'true' );
		$( 'sub' ).textContent = 'Level ' + id + ' · floor ' + ( ( lvMetaLevel( id ) || {} ).res || '-' );
		lvFocusTell( true );
		lvRoomTell( true );
		announcePlan();
		/* The shadow map is about to be redrawn with this level in it for the
		 * first time, and its depth pipelines are the one thing the compile
		 * gate did not build. They are asked for side by side here, through
		 * the same hook the boot uses, so no frame waits on one. */
		if ( PIPES ) { pipesGather(); pipesSettled(); }
		controls.enabled = false;
		fly.enabled = EMBED;
		mode = 'hero';
		setCompare( false );
		if ( towerPlane.constant > towerTop ) towerPlane.constant = towerTop;
		animateSlice( towerPlane, L.z + LV_CUT, FLOOR_IN, 0 );
		const pose = u ? lvFocusPose() : planPose();
		if ( ! fromStreet ) { pose.lift = 0; pose.ease = easeInOut; }
		flyCamera( pose, fromStreet && ! u ? FLOOR_IN : FOCUS_DUR + 400, 0, () => setMode( 'hero' ) );
		shadowDirty();
		invalidate();
	} finally { sceneSettling = false; flyApply(); }
	lvBadgeTell( true );
}

/* Back to the street: the building closes over the level the way it opened,
 * and the level goes away behind it - it stays parsed, so coming back to it
 * costs nothing. */
function lvLeave( animate = true ) {
	const id = lvOpen;
	sceneSettling = true;
	try {
		tweens.length = 0;
		sceneNo = 1;
		lvFocusK = 0; lvHotK = 0; lvRooms = [];
		roomFocus = - 1;
		lvInsideSet( false );
		announce( 'scene', { scene: 1, floor: 0, view: 'street' } );
		$( 's_1' ).setAttribute( 'aria-pressed', 'true' );
		$( 's_2' ).setAttribute( 'aria-pressed', 'false' );
		$( 'sub' ).textContent = 'Street · the solved shot';
		lvBadgeTell( true );
		lvFocusTell();
		lvRoomTell();
		lvRoomDotTell();
		const done = () => {
			towerPlane.constant = 1e4;
			if ( lvOpen === id && sceneNo === 1 ) {
				lvShow( id, false );
				lvOpen = null;
				lvPlane.constant = 1e4;
			}
			shadowDirty();
			invalidate();
		};
		if ( ! animate ) { done(); setMode( 'hero' ); return; }
		controls.enabled = false;
		fly.enabled = EMBED;
		mode = 'hero';
		animateSlice( towerPlane, towerTop, FLOOR_IN, 0, done );
		const back = heroPose();
		back.lift = 0;
		back.ease = easeInOut;
		flyCamera( back, FLOOR_IN, 0, () => setMode( 'hero', true ) );
		invalidate();
	} finally { sceneSettling = false; flyApply(); }
}

/* `setScene` as the rest of the file and the old page still call it. Scene
 * 2 is a level now: a storey number opens that level, no storey opens the
 * show flat's. */
function lvSetScene( n, animate, floor, view ) {
	if ( bwOn ) { if ( n !== 2 ) return bwExit( 'street' ); bwExit( 'none' ); }
	if ( n === 2 ) {
		if ( view === 'plan' && floor ) return lvOpenLevel( lvOfStorey( floor ) );
		const want = lvShowFlat();
		if ( want ) return lvOpenFlat( want );
		LVL.planMeta().then( ( pm ) => { lvPM = pm; const w = lvShowFlat(); if ( w ) lvOpenFlat( w ); }, () => {} );
		return true;
	}
	if ( sceneNo === 2 ) return lvLeave( animate );
	return null;           // already in the street: the old path settles it
}

/* The plate's own box in plan metres for `planFrame`: the level's extent,
 * standing on its floor. The WHOLE L is fitted to the clear part of the
 * window - one level is one plate, and a plate run off the right is half a
 * floor plan. */
function lvFrameBox() {
	const L = lvLevel( lvOpen );
	if ( ! L || ! frameP ) return null;
	if ( ! L.box ) L.box = LVL.levelBox( L );
	const o = frameP.o.clone();
	o.y += L.z;
	return { o, ex: frameP.ex, ey: frameP.ey, x0: L.box.x0, x1: L.box.x1, y0: L.box.y0, y1: L.box.y1,
		fitClear: true };
}
function lvCenter() {
	const B = lvFrameBox();
	if ( ! B ) return siteCenter();
	return B.o.clone().addScaledVector( B.ex, ( B.x0 + B.x1 ) / 2 ).addScaledVector( B.ey, ( B.y0 + B.y1 ) / 2 );
}

/* The floor view's shot, whichever of its three it is on. */
function lvShot() {
	if ( bwOn ) return bwPlace( bwS );
	if ( ! lvOpen ) return;
	if ( roomFocus >= 0 ) return lvRoomShot();
	applyPose( lvFocusK ? lvFocusPose() : planPose() );
}

/* ------------------------------------------------- the drawing's dials */
const lvDrawOwns = () => PLAN2D && sceneNo === 2 && scene2View === 'plan' && !! lvOpen;
let lvPinK = 0;
/* For the rigs: hold flat `k` of the open level at dial `t` (k 0 lets go). */
window.__lvPin = ( k, t = 1 ) => {
	lvPinK = k | 0;
	if ( lvPinK ) { lvRev[ lvPinK ] = lvRevT[ lvPinK ] = t; LVL.LVU.rev.array[ lvPinK ] = t; lvHotK = lvPinK; }
	else { lvHotK = 0; }
	invalidate( SETTLE );
	return { k: lvPinK, rev: lvRev[ lvPinK ] };
};
function lvRevealStep( dt ) {
	if ( lvPinK ) return false;              // held still for a measurement
	const live = lvDrawOwns() && ! lvInside;
	if ( live && planHold > 0 ) planHold = Math.max( 0, planHold - dt );
	let moved = false;
	const want = ( live && planHold <= 0 ) ? 1 : 0;
	if ( lvAmt !== want ) {
		const d = dt / ( want ? PLAN_DRAIN : PLAN_FILL );
		lvAmt = want > lvAmt ? Math.min( 1, lvAmt + d ) : Math.max( 0, lvAmt - d );
		LVL.LVU.amt.value = lvAmt;
		moved = true;
	}
	const L = lvLevel( lvOpen );
	const N = L ? Math.min( L.units.length, LVL.MAX_UNITS - 1 ) : 0;
	for ( let k = 1; k <= N; k ++ ) {
		const w = ( lvDrawOwns() && ( k === lvHotK || k === lvFocusK ) ) ? 1 : 0;
		if ( lvRevT[ k ] === w ) continue;
		const d = dt / ( w ? PLAN_IN : PLAN_OUT );
		lvRevT[ k ] = w > lvRevT[ k ] ? Math.min( 1, lvRevT[ k ] + d ) : Math.max( 0, lvRevT[ k ] - d );
		lvRev[ k ] = easeInOut( lvRevT[ k ] );
		LVL.LVU.rev.array[ k ] = lvRev[ k ];
		/* The furniture's cue: the kits grow their pieces off this dial -
		 * the level's own furniture here (`lvFurn`), and anyone else's off
		 * the hook. The sun's map is drawn again once a flat has arrived or
		 * gone, not on every frame of it. */
		const FP = lvParts.get( lvOpen );
		if ( FP && FP.furn ) {
			FP.furn.reveal( L.units[ k - 1 ].token, lvRev[ k ] );
			if ( lvRevT[ k ] === w ) shadowDirty();
		}
		LVL.hooks.fire( 'onFlatReveal', lvOpen, L.units[ k - 1 ].n, lvRev[ k ] );
		moved = true;
	}
	const wantDim = ( lvDrawOwns() && lvFocusK ) ? PLAN_DIM : 0;
	if ( lvDim !== wantDim ) {
		const d = dt / PLAN_DIM_T;
		lvDim = wantDim > lvDim ? Math.min( wantDim, lvDim + d ) : Math.max( wantDim, lvDim - d );
		LVL.LVU.dim.value = lvDim;
		moved = true;
	}
	if ( ! moved ) return false;
	LVL.LVU.seed.value = ( LVL.LVU.seed.value + 0.6180339887 ) % 1.0;
	lvBadgeTell();
	invalidate( SETTLE );
	return true;
}

/* Which flat is under the pointer in the floor view: a ray to the plane
 * 1.1 m over the level's floor and a point-in-polygon on the flats' own
 * polygons and their loggias - any shape, up to all of them. */
const _lvhit = new THREE.Vector3();
function lvUnitUnder( px ) {
	const L = lvLevel( lvOpen );
	if ( ! px || ! L ) return 0;
	const r = renderer.domElement.getBoundingClientRect();
	_plndc.set( ( px[ 0 ] - r.left ) / r.width * 2 - 1, - ( ( px[ 1 ] - r.top ) / r.height ) * 2 + 1 );
	_plray.setFromCamera( _plndc, camera );
	_plplane.set( _plplane.normal.set( 0, 1, 0 ), - ( L.z + 1.1 ) );
	if ( ! _plray.ray.intersectPlane( _plplane, _lvhit ) ) return 0;
	const [ x, y ] = frameP.plan( _lvhit );
	for ( const u of L.units )
		if ( LVL.inPoly( u.poly, x, y ) || ( u.loggias || [] ).some( p => LVL.inPoly( p, x, y ) ) ) return u.k;
	return 0;
}
function lvHoverTest() {
	if ( ! lvDrawOwns() || lvFocusK || roomFocus >= 0 ) return;
	const k = lvUnitUnder( floorPointer );
	if ( k === lvHotK ) return;
	lvHotK = k;
	if ( renderer && EMBED ) renderer.domElement.style.cursor = k ? 'pointer' : 'grab';
	invalidate( 2 );
}

/* ------------------------------------------------- the badges
 * One per flat at its own label point (plan_meta `label_at`), carrying the
 * flat's number and its total area - the page draws them. And the three
 * entrances, at their cores, which the page names. */
const _lvq = new THREE.Vector3();
let lvBadgeSaid = '';
function lvBadgeTell( force = false ) {
	if ( ! lvDrawOwns() ) {
		if ( lvBadgeSaid === '' && ! force ) return;
		lvBadgeSaid = '';
		announce( 'planbadge', { badges: [], entrances: [], on: false } );
		return;
	}
	const L = lvLevel( lvOpen );
	if ( ! L ) return;
	const r = renderer.domElement.getBoundingClientRect();
	const at = ( x, y, z ) => {
		frameP.world( x, y, z, _lvq ).project( camera );
		return [ Math.round( ( _lvq.x * 0.5 + 0.5 ) * r.width + r.left ),
			Math.round( ( - _lvq.y * 0.5 + 0.5 ) * r.height + r.top ), _lvq.z < 1 ];
	};
	const show = lvAmt > 0.5 && ! lvFocusK;
	const out = L.units.map( ( u ) => {
		/* In the middle of the flat, as the architect's sheets letter them -
		 * the flat's own pole, not `label_at`: plan_meta's label point sits
		 * by the flat's entrance, and on a double-loaded bar the two rows'
		 * entrance labels are 4 m apart and their badges collide over the
		 * corridor. `label_at` is the fallback. */
		if ( ! u.mid ) u.mid = u.poly ? LVL.poleOf( u.poly ) : u.label_at;
		const p = u.mid || u.label_at;
		const [ x, y, front ] = at( p[ 0 ], p[ 1 ], L.z + 1.2 );
		return { x, y, on: ( show && front && u.k !== lvHotK ) ? 1 : 0,
			n: u.office ? null : u.n, office: u.office ? u.n : null,
			area: u.area ? u.area.total : null, level: L.id,
			poly: L.id + '-' + ( u.office ? 'o' : 'u' ) + u.n };
	} );
	// the residents' three cores; the podium's own stair is not an entrance
	const ent = ( ( lvPM && lvPM.cores ) || [] ).map( ( c, i ) => {
		if ( ! c.hall || ! /^C\d+$/.test( c.id ) ) return null;
		if ( ! c.at ) c.at = LVL.poleOf( c.hall );
		const [ x, y, front ] = at( c.at[ 0 ], c.at[ 1 ], L.z + 1.2 );
		return { x, y, core: c.id, k: + ( /\d+/.exec( c.id ) || [ i + 1 ] )[ 0 ], on: ( show && front ) ? 1 : 0 };
	} ).filter( Boolean );
	const key = out.map( p => p.x + ',' + p.y + ',' + p.on ).join( ';' ) + '|'
		+ ent.map( p => p.x + ',' + p.y + ',' + p.on ).join( ';' );
	if ( ! force && key === lvBadgeSaid ) return;
	lvBadgeSaid = key;
	announce( 'planbadge', { badges: out, entrances: ent, on: true, level: L.id } );
}

/* ------------------------------------------------- one flat */
function lvFocusBox( u ) {
	return LVL.bboxOf( [ u.poly, ...( u.loggias || [] ) ] );
}
function lvFocusPose() {
	const L = lvLevel( lvOpen ), u = lvUnit( lvFocusK );
	if ( ! L || ! u ) return planPose();
	return planFocusPose( - 1, { box: lvFocusBox( u ), F: planFrame(),
		head: ( L.clear || L.h - 0.3 ) - 0.2 } );
}
/* Open one flat (a unit record of the open level), or close it with null. */
function lvFocus( u, animate = true ) {
	if ( ! lvDrawOwns() ) return;
	const k = u ? u.k : 0;
	if ( k === lvFocusK && roomFocus < 0 ) return;
	planKillTween();
	planDrag = null;
	planVel = 0;
	roomFocus = - 1;
	roomSaid = - 2;
	lvInsideSet( false );
	lvFocusK = k;
	if ( k ) lvHotK = k;
	else { lvHotK = 0; floorDirty = true; }
	lvRooms = u ? LVL.roomsOf( u, lvLite ) : [];
	// the walk's engine, so a room's stance can be checked against its walls (`lvRoomLook`)
	if ( u && ! bwW ) bwEngine().catch( () => {} );
	lvRoomTell();
	lvFocusTell();
	announcePlan();
	const pose = k ? lvFocusPose() : planPose();
	if ( animate ) planFocusFly( pose );
	else { applyPose( pose ); setMode( 'hero' ); }
	lvBadgeTell( true );
	invalidate();
}
let lvFocusSaid = '~';
function lvFocusTell( force = false ) {
	const u = ( sceneNo === 2 && lvOpen ) ? lvUnit( lvFocusK ) : null;
	const key = u ? lvOpen + '/' + u.k : '';
	if ( ! force && key === lvFocusSaid ) return;
	lvFocusSaid = key;
	const was = sceneSettling;
	sceneSettling = true;
	try {
		announce( 'planfocus', { n: u && ! u.office ? u.n : null, office: u && u.office ? u.n : null,
			level: lvOpen, unit: u ? u.k : - 1, floor: lvStorey( lvOpen ),
			poly: u ? lvOpen + '-' + ( u.office ? 'o' : 'u' ) + u.n : null } );
	} finally { sceneSettling = was; }
}

/* ------------------------------------------------- its rooms */
const lvRoomOwns = () => lvDrawOwns() && lvFocusK > 0 && roomFocus >= 0;
function lvRoomPose( i ) {
	const L = lvLevel( lvOpen ), R = lvRooms[ i ];
	if ( ! L || ! R ) return lvFocusPose();
	const p = frameP.world( R.eye[ 0 ], R.eye[ 1 ], L.z + ( R.eye[ 2 ] ?? 1.6 ) );
	const look = lvRoomLook( R );
	const t = frameP.world( look[ 0 ], look[ 1 ], L.z + ( look[ 2 ] ?? 1.2 ) );
	const tmp = new THREE.PerspectiveCamera( LV_ROOM_FOV, frameAspect(), 0.1, 4000 );
	tmp.position.copy( p );
	tmp.up.set( 0, 1, 0 );
	tmp.lookAt( t );
	return { p, q: tmp.quaternion.clone(), fov: LV_ROOM_FOV, shift: 0, target: t };
}
/* Where a room's stance looks. The stance rooms.json gives is kept - unless,
 * read off the walk's own collision field, it faces a wall within 1.2 m
 * (build 3: a few of them stood a visitor nose to a partition). Then the
 * eye turns down the longest free line across the room from the same spot
 * (walk.js `sight`). The engine is made when a flat opens, so it is
 * normally there by the time a dot is clicked; if not, the stance stands. */
const LV_FACE_MIN = 1.2;
function lvRoomLook( R ) {
	if ( ! bwW || ! lvOpen || ! R.eye || ! R.look ) return R.look;
	if ( R.lookFixed ) return R.lookFixed;
	const h = Math.atan2( R.look[ 1 ] - R.eye[ 1 ], R.look[ 0 ] - R.eye[ 0 ] );
	let S = null;
	try { S = bwW.sight( lvOpen, R.eye[ 0 ], R.eye[ 1 ], h ); } catch ( e ) { S = null; }
	if ( ! S ) return R.look;
	R.lookFixed = S.free >= LV_FACE_MIN ? R.look
		: [ R.eye[ 0 ] + Math.cos( S.best ) * 3, R.eye[ 1 ] + Math.sin( S.best ) * 3, R.look[ 2 ] ?? 1.2 ];
	return R.lookFixed;
}
function lvRoomShot( aim = false ) {
	if ( roomFocus < 0 || ! lvFocusK ) return;
	const P = lvRoomPose( roomFocus );
	if ( ! aim ) P.q = camera.quaternion.clone();
	applyPose( P );
	if ( fly ) fly.sync();
}
function lvRoomSet( i, animate = true ) {
	if ( ! lvDrawOwns() || ! lvFocusK ) return;
	const n = ( i != null && i >= 0 && i < lvRooms.length ) ? i | 0 : - 1;
	if ( n === roomFocus ) return;
	const inside = roomFocus >= 0;
	roomFocus = n;
	lvRoomTell();
	lvRoomDotTell();
	LVL.hooks.fire( 'onRoom', lvOpen, ( lvUnit( lvFocusK ) || {} ).n, n >= 0 ? lvRooms[ n ] : null );
	const to = n >= 0 ? lvRoomPose( n ) : lvFocusPose();
	const lift = ( inside && n >= 0 ) ? null : n >= 0 ? 'in' : 'out';
	/* Coming out, the plan comes back at once rather than when the camera
	 * passes up through the ceiling: the last thing the flight out may do is
	 * arrive at a plan with a lid on it. */
	if ( n < 0 ) lvInsideSet( false );
	if ( animate ) roomFly( to, lift ? ROOM_DUR : ROOM_STEP, lift );
	else { applyPose( to ); setMode( 'hero' ); if ( fly ) fly.sync(); lvInsideStep(); }
	shadowDirty();
	invalidate();
}
function lvRoomTell( force = false ) {
	const i = lvRoomOwns() ? roomFocus : - 1;
	if ( ! force && i === roomSaid ) return;
	roomSaid = i;
	const R = i >= 0 ? lvRooms[ i ] : null;
	const was = sceneSettling;
	sceneSettling = true;
	try {
		announce( 'room', { room: i, key: R ? R.kind : null, name: R ? R.name : null,
			ka: R ? R.ka : null, count: lvRooms.length, unit: lvFocusK, level: lvOpen,
			n: ( lvUnit( lvFocusK ) || {} ).n || null } );
	} finally { sceneSettling = was; }
}
let lvDotSaid = '';
function lvRoomDotTell( force = false ) {
	const L = lvLevel( lvOpen );
	const live = lvDrawOwns() && lvFocusK > 0 && roomFocus < 0 && lvRooms.length && L;
	if ( ! live ) {
		if ( lvDotSaid === '' && ! force ) return;
		lvDotSaid = '';
		announce( 'roomdot', { dots: [], on: false } );
		return;
	}
	const r = renderer.domElement.getBoundingClientRect();
	const out = lvRooms.map( ( R ) => {
		frameP.world( R.label[ 0 ], R.label[ 1 ], L.z + 1.2, _lvq ).project( camera );
		return { i: R.i, name: R.name, ka: R.ka, key: R.kind,
			x: Math.round( ( _lvq.x * 0.5 + 0.5 ) * r.width + r.left ),
			y: Math.round( ( - _lvq.y * 0.5 + 0.5 ) * r.height + r.top ),
			on: _lvq.z < 1 ? 1 : 0 };
	} );
	const key = out.map( p => p.x + ',' + p.y + ',' + p.on ).join( ';' );
	if ( ! force && key === lvDotSaid ) return;
	lvDotSaid = key;
	announce( 'roomdot', { dots: out, on: true } );
}

/* Under its own ceiling the camera wants the room WHOLE: the clip lifted,
 * the cap gone, and the storeys over it back, or the walls stop at 1.45 m
 * and the sky shows over them. Checked on the frame, so it changes as the
 * dive passes down through the ceiling, edge on, where nobody sees it. */
function lvInsideStep() {
	/* Walking, the walk owns the cut (none) - except on the dive down into a
	 * flat from the floor view, which lifts it as it passes the ceiling. */
	if ( bwOn && ( bwFrom === 'street' || ! tweens.length ) ) return;
	const L = lvLevel( lvOpen );
	lvInsideSet( !! L && sceneNo === 2 && ( roomFocus >= 0 || bwOn )
		&& camera.position.y < L.z + ( L.clear || L.h - 0.3 ) - 0.02 );
}
function lvInsideSet( want ) {
	if ( want === lvInside ) return;
	lvInside = want;
	const L = lvLevel( lvOpen );
	lvPlane.constant = ( want || ! L ) ? 1e4 : L.z + LV_CUT;
	if ( L && sceneNo === 2 ) towerPlane.constant = want ? 1e4 : L.z + LV_CUT;
	const P = lvParts.get( lvOpen );
	if ( P && P.cap ) P.cap.visible = ! want;
	roomShadow( want );
	shadowDirty();
	invalidate( 2 );
}

/* What other modules may ask of the scene - see `LVL.hooks`. */
LVL.hooks.shown = () => ( sceneNo === 2 ? lvOpen : null );
LVL.hooks.groupOf = ( id ) => { const P = lvParts.get( id ); return ( P && P.state === 'in' ) ? P.group : null; };
LVL.hooks.doorsOf = ( id ) => { const P = lvParts.get( id ); return P ? P.doors : []; };

/* window.LP, the real-building half. Installed over the old members of the
 * same names, so the page's existing calls land here. */
function lvInstallApi( LP ) {
	Object.defineProperties( LP, Object.getOwnPropertyDescriptors( {
		openLevel: ( id ) => lvOpenLevel( String( id ) ),
		openFlat: ( n ) => lvOpenFlat( n ),
		closeFlat: () => {
			if ( bwOn ) return bwExit( 'plan' );
			if ( roomFocus >= 0 ) lvRoomSet( - 1, false );
			if ( lvFocusK ) lvFocus( null );
		},
		get showFlat() { return lvShowFlat(); },
		levelOf: ( n ) => { const u = LVL.flatByN( n ); return u ? u.level : null; },
		get level() { return sceneNo === 2 ? lvOpen : null; },
		get flat() { const u = lvUnit( lvFocusK ); return u && ! u.office ? u.n : null; },
		get floor() { return lvOpen ? lvStorey( lvOpen ) : topFloor(); },
		setScene: ( n, floor, view ) => setScene( n, true, floor || topFloor(), view || 'hero' ),
		get planSteps() { return 0; },
		get planFocus() { return lvFocusK ? lvFocusK : - 1; },
		planFocusTo: ( i ) => { if ( i == null || i < 0 ) lvFocus( null ); else lvFocus( lvUnit( i | 0 ) ); },
		get room() { return lvRoomOwns() ? roomFocus : - 1; },
		get rooms() { return lvRooms.map( R => ( { i: R.i, key: R.kind, name: R.name, ka: R.ka } ) ); },
		roomTo: ( i ) => {
			// out of a room on foot is out to the flat it is in
			if ( bwOn && ( i == null || i < 0 ) ) return bwExit( 'plan' );
			if ( bwOn ) bwExit( 'none' );
			return lvRoomSet( i == null ? - 1 : i | 0 );
		},
		roomBy: ( d ) => {
			if ( roomFocus < 0 || ! lvRooms.length ) return;
			lvRoomSet( ( roomFocus + ( d | 0 ) + lvRooms.length * 2 ) % lvRooms.length );
		},
		/* On foot (see "walking the building"): `walk( {portal: 'C1'} )`,
		 * `walk( {flat: '37'} )`, `walk( {flat, room} )`, `walk( {level, at:
		 * [x, y], heading} )`; `entrance( k )` is portal C<k>; `walkExit(
		 * 'street' | 'plan' )`; `liftGo( level )` in a car; `walkMap` takes
		 * the canvas the minimap is drawn into. */
		walk: ( spec ) => {
			if ( ! spec ) return false;
			if ( spec.flat != null && spec.room == null && ! spec.at ) return bwWalkFlat( spec.flat );
			return bwWalk( spec, { from: spec.portal ? 'street' : 'level' } );
		},
		entrance: ( k ) => bwWalk( { portal: /^\d$/.test( String( k ) ) ? 'C' + k : String( k ) }, { from: 'street' } ),
		walkExit: ( to ) => bwExit( to || null ),
		liftGo: ( level ) => !! ( bwOn && bwW && bwW.liftGo( level ) && ( invalidate( 2 ), true ) ),
		get walking() { return bwOn; },
		get walkState() { return bwOn ? bwS : null; },
		set walkMap( c ) { bwMapEl = c || null; bwMapCache.clear(); bwMapDraw(); },
		get walkMap() { return bwMapEl; },
	} ) );
	return LP;
}
/* For the rigs: where on the screen a storey's band is - face line `f` of
 * meta.facades, `t` along it, half way up level `id` - or null off screen. */
window.__lvBandAt = ( id, f, t = 0.5 ) => {
	const L = lvMetaLevel( id ), F = meta && meta.facades && meta.facades[ f ];
	if ( ! L || ! F || ! frameP ) return null;
	const x = F.a[ 0 ] + ( F.b[ 0 ] - F.a[ 0 ] ) * t + F.out[ 0 ] * 0.1;
	const y = F.a[ 1 ] + ( F.b[ 1 ] - F.a[ 1 ] ) * t + F.out[ 1 ] * 0.1;
	const v = frameP.world( x, y, L.z + L.h * 0.5 ).project( camera );
	const r = renderer.domElement.getBoundingClientRect();
	if ( v.z > 1 || Math.abs( v.x ) > 0.98 || Math.abs( v.y ) > 0.98 ) return null;
	return [ Math.round( ( v.x * 0.5 + 0.5 ) * r.width + r.left ), Math.round( ( - v.y * 0.5 + 0.5 ) * r.height + r.top ) ];
};
/* For the rigs: the walk's engine and its state, and a way to drive it a
 * fixed step at a time with given input (`__bw.step( n, input )`), so a
 * headless tour walks the same body the keys do. */
window.__bw = {
	get on() { return bwOn; }, get s() { return bwS; }, get W() { return bwW; },
	get shown() { return [ ...bwShown ]; },
	ready: ( id ) => bwHere( id ),
	/* What the tour rig asks every frame: is the body standing (or on a
	 * flight, or at an open car door) on a storey that is not on screen? */
	hole() {
		if ( ! bwOn || ! bwS ) return null;
		const s = bwS, miss = [];
		const C = lvParts.get( 'cores' );
		if ( s.surface !== 'street' && ! ( C && C.group && C.group.visible ) ) miss.push( 'cores' );
		const riding = !! ( s.inLift && s.inLift.riding );
		if ( s.surface !== 'street' && s.level !== 'ROOF' && ! bwShown.has( s.level ) ) miss.push( s.level );
		// a car sees its shaft, which is the walls of the storeys it passes
		if ( riding ) for ( const id of s.needLevels ) if ( id !== 'ROOF' && ! bwShown.has( id ) && Math.abs( ( lvMetaLevel( id ) || { z: 1e9 } ).z - s.pos.plan[ 2 ] ) < 3.4 ) miss.push( id + '(shaft)' );
		if ( s.onStair ) for ( const id of s.seesLevels || s.needLevels ) if ( id !== 'ROOF' && ! bwShown.has( id ) ) miss.push( id );
		for ( const l of s.lifts ) if ( l.doorOpen > 0 && l.level && l.level !== 'ROOF' && Math.abs( l.z - s.pos.plan[ 2 ] ) < 1.5
			&& ! bwShown.has( l.level ) ) miss.push( l.level + '(lift door)' );
		return miss.length ? [ ...new Set( miss ) ] : null;
	},
	step( n, input = {}, dt = 1 / 60 ) {
		if ( ! bwOn || ! bwW ) return null;
		// the look is a turn made once, not once a step
		const rest = input.look ? Object.assign( {}, input, { look: null } ) : input;
		for ( let i = 0; i < n; i ++ ) { bwS = bwW.step( dt, i ? rest : input ); bwApply( bwS, false ); }
		bwApply( bwS, true ); bwTell(); bwMapDraw();
		if ( fly ) { fly.sync(); bwLookAt = fly.look; }
		invalidate( 4 );
		const s = bwS;
		if ( s.surface !== 'street' ) bwBeenIn = true;
		else if ( bwOutside( s ) > ( bwBeenIn ? BW_OUT : BW_OUT_UNVISITED ) ) bwExit( 'street' );
		return s;
	},
	parts: () => [ ...lvParts.values() ].map( P => ( { name: P.name, state: P.state, shown: !! ( P.group && P.group.visible ),
		furn: P.furnState || null, out: P.movers ? P.movers.out.size : 0, standing: P.furn ? P.furn.standing() : null } ) ),
	near: () => camera.near, leaf: () => !! ( groups.leaf && groups.leaf.visible ),
	cut: () => ( { lv: lvPlane.constant, tower: towerPlane.constant } ),
};
/* For the rigs and the console: what is resident, what it cost. */
window.__lv = () => ( {
	open: lvOpen, scene: sceneNo, focus: ( lvUnit( lvFocusK ) || {} ).n || null, hot: lvHotK,
	hotLevel: lvHotLevel, waiting: lvWaiting, amt: + lvAmt.toFixed( 3 ), inside: lvInside,
	room: roomFocus, rooms: lvRooms.map( R => R.name ),
	parts: [ ...lvParts.values() ].map( P => ( { name: P.name, state: P.state, shown: !! ( P.group && P.group.visible ),
		meshes: P.group ? P.group.children.length : 0, tris: Math.round( P.tris ) } ) ),
	bytes: LVL.partBytes(),
	shownMeshes: lvOpen && lvParts.get( lvOpen ) && lvParts.get( lvOpen ).group
		? lvParts.get( lvOpen ).group.children.filter( o => o.isMesh && o.visible ).length : 0,
	cut: lvPlane.constant, tower: towerPlane.constant, tweens: tweens.length, compiling,
} );

/* ================================================== walking the building
 * A visitor on foot, anywhere in the architect's building: in through a
 * street door, up the stairs or in a lift, along a corridor, into a flat
 * and out onto its loggia - and back out to the street, in one go.
 *
 * The body is web/walk.js's (the engine: floors, stairs, lifts, doors,
 * collision, the gait the owner approved in the old show flat). This is the
 * host: it hands the engine the keys and the pointer, and it puts on the
 * screen what the engine says is true - the levels the body can see, the
 * leaves swung to the engine's angles, the cars in their shafts.
 *
 *   ways in   a room of an open flat (the room dots: landing in a room IS
 *             walking); a street door - the three entrance doors and the
 *             terrace stair's, clicked in the street, or the page's
 *             "Entrance 1/2/3" - the camera walks up to it and hands over;
 *             `LP.walk( {portal|flat|level, at, room} )`; #walk-C1,
 *             #flat-37/walk.
 *   the gate  the engine is asked, per level, whether its geometry is HERE
 *             (`bwReady`: the level's interior welded and compiled, its
 *             furniture in or known absent, the cores in), and it never
 *             lets the body onto a surface of a level that is not - the
 *             visitor waits at a shut door or a landing, or in a car with
 *             its doors shut, and the level arrives while they do. The
 *             engine's `needLevels` (the body's storey, and both ends of a
 *             flight it is near) is what is fetched; a ride fetches only
 *             where it is going.
 *   inside    no cut: full-height walls and ceilings, both blocks' envelope
 *             and the city kept (the windows look out onto the real street),
 *             the levels in `needLevels` shown and the rest hidden, near
 *             plane 0.10 (WALK.NEAR), the sun's shadow fitted to the room -
 *             a flat's reach in a flat, further in a corridor or a stair.
 *   render    on demand, as everywhere: the engine says `moving` and a frame
 *             is owed; standing still, nothing is drawn.
 *
 * Rigs: tools/tourcheck.cjs (two tours through the real page),
 * tools/walkcheck.cjs, tools/walkbuilding.cjs (the engine alone).
 * -------------------------------------------------------------------- */
const BW_FOV = LV_ROOM_FOV;
/* The sun's reach under a ceiling: a flat is ~12 m across, a corridor and a
 * stairwell are not - past the far plane nothing is shadowed and the sun
 * would light a corridor's far end through its walls. */
const BW_SHADOW_FLAT = 24, BW_SHADOW_COMMON = 60;
/* How far onto the street a body walks before the walk hands back to the
 * street's own shot. The doorstep reaches 2.7 m out (walk.js `apron`), so a
 * body can stand 2.46 m out at most; a way in from the street stands it at
 * 2.2. Out of the building it is 2.0 m - a step clear of the door - and
 * from a body that has not been in yet, the very edge of the step. */
const BW_OUT = 2.0, BW_OUT_UNVISITED = 2.4;
let bwBeenIn = false;
/* While walking, how many levels may stay parsed (the body's, a neighbour on
 * a stair, a car's destination) before the least recently wanted goes. */
const BW_RESIDENT = 4;

let bwW = null, bwMaking = null;   // the engine, made once plan_meta is in
let bwOn = false;                  // a visitor is walking
let bwS = null;                    // the engine's last state
let bwFrom = null;                 // 'street' | 'level' | 'room': where they came in
let bwAsk = 0;
let bwHot = null;                  // the street door under the pointer
let bwPick = null;                 // its hit quads
let bwLookAt = { yaw: 0, pitch: 0 };
let bwTouch = null;                // a thumb on the left half of the window
let bwShown = new Set();           // levels on screen while walking
const bwOut = new Map();           // node -> level: leaves the engine has open
let bwSaid = '', bwMapEl = null, bwMapLv = null, bwMapCache = new Map();
let bwStreetLeaves = null;         // the street's stand-in leaves (scene_meta)
let bwShadowFar = 0, bwSig = '';
let bwEnded = 0;                   // performance.now() when the last walk ended
const bwAhead = new Set();         // car+storey whose neighbours have been asked for
/* RIDE_AHEAD: the storeys either side are asked for where the car STANDS,
 * not for every storey it passes (each was a furniture fetch, decode and
 * weld, mostly evicted again before the stop). `?rideahead=old` as before.
 * RIDE_FIELDS: walk.js builds no field for a storey passed and asks the
 * worker for the stop's; `?ridefields=old` as before. */
const RIDE_AHEAD_OLD = __q.get( 'rideahead' ) === 'old';
const RIDE_FIELDS_OLD = __q.get( 'ridefields' ) === 'old';

/* The engine, once: it reads plan_meta and nothing else. */
function bwEngine() {
	if ( bwW ) return Promise.resolve( bwW );
	if ( bwMaking ) return bwMaking;
	bwMaking = LVL.planMeta().then( ( pm ) => {
		lvPM = pm;
		bwW = createWalker( { meta, planMeta: pm, worker: true, rideFieldsOld: RIDE_FIELDS_OLD,
			toWorld: ( x, y, z ) => frameP.world( x, y, z, _bwv ).toArray(),
			ready: bwReady, on: bwEvent } );
		// solids for levels whose furniture is already in
		for ( const P of lvParts.values() ) if ( P.furnSolids ) bwW.solids( P.name, P.furnSolids );
		return bwW;
	} );
	bwMaking.catch( () => { bwMaking = null; } );
	return bwMaking;
}
const _bwv = new THREE.Vector3();

/* Is the geometry HERE: the level's interior welded and compiled, its
 * furniture in (or known to have none), and the cores - every storey's
 * stairs and lifts - in too. ROOF is the stair heads, in cores.glb. */
const lvIn = ( id ) => { const P = lvParts.get( id ); return !! P && P.state === 'in'; };
/* MEASUREMENT ONLY: `?bwgate=0` tells the engine every level is here, so
 * tools/tourcheck.cjs can be shown to FAIL (a body on a storey that is not on
 * screen) against the bug the gate guards. Nothing else may use it. */
const BW_GATE = __q.get( 'bwgate' ) !== '0';
function bwReady( id, why ) { return ! BW_GATE || bwHere( id, why ); }
/* `why` 'shaft': a car going past only needs the storey's walls - its
 * furniture is behind them. */
function bwHere( id, why ) {
	if ( ! lvIn( 'cores' ) ) return false;
	if ( id === 'ROOF' ) return true;
	const P = lvParts.get( id );
	return !! P && P.state === 'in' && ( why === 'shaft' || P.furnState === 'in' || P.furnState === 'none' );
}
/* Ask for what the engine says it needs: each level and its furniture, and
 * the cores. Nothing is SHOWN here - `bwApply` shows what is ready. */
function bwWant( ids, furn = true ) {
	lvPart( 'cores' ).catch( () => {} );
	for ( const id of ids ) {
		if ( id === 'ROOF' || id === 'P-1' ) continue;
		const P = lvParts.get( id );
		if ( P && P.state === 'in' ) { P.usedAt = performance.now(); if ( furn && ! P.furnReady ) lvFurn( P ); continue; }
		lvPart( id ).then( ( Q ) => { if ( furn ) lvFurn( Q ); }, () => {} );
	}
}
function bwAllReady( ids ) {
	return ids.every( id => bwHere( id ) );
}
function bwUntilReady( ids, ask, ms = 30000 ) {
	return new Promise( ( res ) => {
		const t0 = performance.now();
		const poll = () => {
			if ( ask !== bwAsk ) return res( false );
			if ( bwAllReady( ids ) ) return res( true );
			if ( performance.now() - t0 > ms ) return res( false );
			setTimeout( poll, 60 );
		};
		poll();
	} );
}

/* The engine's events: the page hears about levels, flats, rooms, lifts. */
function bwEvent( type, p ) {
	if ( type === 'door' || type === 'arrive' ) invalidate( 2 );
	if ( type === 'level' && bwOn ) { lvOpen = p.level === 'ROOF' ? lvOpen : p.level; bwTell( true ); }
}

/* ------------------------------------------------- the ways in
 * `spec` is the engine's: {portal} | {flat[, room]} | {level, at, heading}.
 * `how`: { from: 'street'|'level'|'room', fly: bool }. Resolves true once
 * the visitor is walking. */
async function bwWalk( spec, how = {} ) {
	if ( ! frameP || ! meta ) return false;
	const ask = ++ bwAsk;
	let W;
	try { W = await bwEngine(); } catch ( e ) { console.warn( 'walk: no plan', e ); return false; }
	if ( ask !== bwAsk ) return false;
	lvLite = lvLite || await LVL.roomsLite();
	const s0 = W.enter( spec );
	if ( ! s0 ) { console.warn( 'walk: nowhere to stand for', spec ); return false; }
	/* A street door needs nothing loaded to stand outside it - the doorstep
	 * is the street's - and the level behind it is fetched while the camera
	 * walks up; the door stays shut until it is in. Anywhere else the body is
	 * IN the building, so nothing is shown until its storey is here. */
	const need = s0.needLevels.filter( id => id !== 'ROOF' );
	if ( spec.portal && ! need.includes( 'L00' ) ) need.push( 'L00' );
	bwWant( need );
	lvWaiting = s0.level;
	embedCursor( false );
	if ( ! spec.portal ) {
		const ok = await bwUntilReady( need, ask );
		if ( ! ok || ask !== bwAsk ) { if ( ask === bwAsk ) { lvWaiting = null; embedCursor( false ); } return false; }
		// the engine placed the body before its furniture was solid: again
		const s1 = W.enter( spec );
		if ( s1 ) Object.assign( s0, s1 );
	}
	lvWaiting = null;
	bwStart( s0, how.from || ( spec.portal ? 'street' : 'level' ), how.fly !== false );
	return true;
}

/* From an open flat's room: the camera has just landed on the room's stance,
 * and from here on it is a body standing there. Nothing moves: the body is
 * put where the camera is, looking where it looks. */
async function bwFromRoom() {
	if ( bwOn || roomFocus < 0 || ! lvFocusK || ! lvOpen ) return;
	const L = lvLevel( lvOpen ), room = roomFocus, lv = lvOpen;
	if ( ! L ) return;
	/* The level is on screen; its furniture (which is solid) may not be
	 * yet. The visitor is stood in the room either way - the keys come
	 * alive once it is here. */
	if ( ! bwHere( lv ) ) {
		bwWant( [ lv ] );
		const ask = bwAsk;
		await bwUntilReady( [ lv ], ask, 20000 );
		if ( bwOn || roomFocus !== room || lvOpen !== lv || tweens.length || ! bwHere( lv ) ) return;
	}
	const at = frameP.plan( camera.position );
	camera.getWorldDirection( _bwv );
	const d = frameP.plan( _bwv.add( camera.position ) );
	const heading = Math.atan2( d[ 1 ] - at[ 1 ], d[ 0 ] - at[ 0 ] );
	const pitch = Math.asin( Math.max( - 1, Math.min( 1, d[ 2 ] - at[ 2 ] ) ) );
	bwEngine().then( ( W ) => {
		if ( bwOn || roomFocus !== room || lvOpen !== lv ) return;
		const s = W.enter( { level: lvOpen, at: [ at[ 0 ], at[ 1 ] ], heading, z: L.z } );
		if ( ! s ) return;
		W.step( 0, { look: { yaw: 0, pitch } } );
		bwStart( W.state(), 'room', false );
	} );
}

/* The walk begins: the scene becomes the walk's, and the camera either is
 * already where the body stands (a room) or walks there (a door, a flat). */
function bwStart( s, from, flyIn ) {
	bwOn = true;
	embedCursor( false );
	bwBeenIn = s.surface !== 'street';
	bwFrom = from;
	bwS = s;
	sceneSettling = true;
	try {
		lvBandsReset();
		bwHotSet( null );
		const was = lvOpen;
		sceneNo = 2;
		scene2View = 'walk';
		roomFocus = - 1;
		roomSaid = - 2;
		lvFocusK = 0; lvHotK = 0; lvRooms = [];
		lvOpen = s.level === 'ROOF' ? ( was || 'L10' ) : s.level;
		// the drawing goes: the walk sees the building as modelled
		lvAmt = 0; LVL.LVU.amt.value = 0; lvDim = 0; LVL.LVU.dim.value = 0;
		lvRev.fill( 0 ); lvRevT.fill( 0 );
		for ( let k = 0; k < LVL.MAX_UNITS; k ++ ) LVL.LVU.rev.array[ k ] = 0;
		lvBadgeTell( true );
		lvFocusTell( true );
		lvRoomTell( true );
		lvRoomDotTell( true );
		announce( 'scene', { scene: 2, view: 'walk', level: lvOpen, floor: lvStorey( lvOpen ) } );
		$( 's_1' ).setAttribute( 'aria-pressed', 'false' );
		$( 's_2' ).setAttribute( 'aria-pressed', 'true' );
		controls.enabled = false;
		mode = 'hero';
		setCompare( false );
		/* Under a ceiling: no cut anywhere, and the levels the body can see
		 * shown whole (`bwApply`). A dive from the floor view keeps the cut
		 * until the camera has passed down through the ceiling - see
		 * `lvInsideStep`, which the dive's frames run. */
		if ( ! flyIn || from === 'street' ) { towerPlane.constant = 1e4; lvPlane.constant = 1e4; lvInside = true; }
		bwApply( s, ! flyIn );
	} finally { sceneSettling = false; }
	if ( flyIn ) {
		const to = bwPose( s );
		/* From the street it is a walk up to the door, low over the
		 * pavement; from the floor view, the room dive. */
		if ( from === 'street' ) { to.lift = 1.5; to.ease = easeInOut; flyCamera( to, 2200, 0, bwLanded ); }
		else roomFly( to, ROOM_DUR, 'in' );
	} else bwLanded();
	flyApply();
	bwTell( true );
	invalidate( SETTLE );
}
/* The camera has arrived where the body stands. */
function bwLanded() {
	if ( ! bwOn ) return;
	towerPlane.constant = 1e4; lvPlane.constant = 1e4; lvInside = true;
	for ( const P of lvParts.values() ) if ( P.cap ) P.cap.visible = false;
	camera.near = BW.NEAR;
	bwPlace( bwS );
	if ( fly ) { fly.sync(); bwLookAt = fly.look; }
	shadowDirty();
	invalidate( SETTLE );
}

/* The pose the engine's state asks for, as `flyCamera` takes it. */
const _bwm = new THREE.Matrix4(), _bwq = new THREE.Quaternion();
function bwPose( s ) {
	const p = new THREE.Vector3( ...s.eye ), t = new THREE.Vector3( ...s.target );
	const tmp = new THREE.PerspectiveCamera( BW_FOV, frameAspect(), BW.NEAR, 2600 );
	tmp.position.copy( p ); tmp.up.set( 0, 1, 0 ); tmp.lookAt( t ); tmp.rotateZ( s.roll || 0 );
	return { p, q: tmp.quaternion.clone(), fov: BW_FOV, shift: 0, pan: 0, target: t };
}
function bwPlace( s ) {
	if ( ! s || tweens.length ) return;
	camera.position.set( s.eye[ 0 ], s.eye[ 1 ], s.eye[ 2 ] );
	camera.up.set( 0, 1, 0 );
	camera.lookAt( s.target[ 0 ], s.target[ 1 ], s.target[ 2 ] );
	if ( s.roll ) camera.rotateZ( s.roll );
	if ( camera.fov !== BW_FOV || camera.lensShift || camera.lensPan || camera.near !== BW.NEAR
		|| Math.abs( camera.aspect - frameAspect() ) > 1e-6 ) {
		camera.fov = BW_FOV; camera.lensShift = 0; camera.lensPan = 0; camera.near = BW.NEAR;
		camera.aspect = frameAspect();
		camera.updateProjectionMatrix();
	}
	if ( controls ) controls.target.copy( _bwv.set( ...s.target ) );
}

/* ------------------------------------------------- the frame
 * Called by the fly controls' `walk` hook - the keys, the drag and the
 * thumb are theirs and this page's, the body is the engine's. Returns true
 * to say it has taken the camera. */
function bwStep( dt, f, r, fast, keys ) {
	if ( ! bwOn || ! bwW ) return false;
	if ( tweens.length ) return true;          // still walking up to it
	/* A level (or its furniture) compiling holds the picture: the body holds
	 * too, so it does not walk on unseen and arrive a jump later. Past
	 * BW_HOLD_CUE the HUD says it is waiting (`bwTell`). */
	if ( compiling ) { bwTell(); return true; }
	const k = ( c ) => keys && keys.has( c ) ? 1 : 0;
	const L = fly.look;
	const look = { yaw: - ( L.yaw - bwLookAt.yaw ), pitch: L.pitch - bwLookAt.pitch };
	const I = {
		forward: f, strafe: k( 'KeyD' ) - k( 'KeyA' ),
		turn: k( 'KeyE' ) + k( 'ArrowRight' ) - k( 'KeyQ' ) - k( 'ArrowLeft' ),
		run: fast, look,
	};
	if ( bwTouch ) { I.forward = bwTouch.f; I.strafe = bwTouch.r; }
	const s = bwW.step( dt, I );
	bwS = s;
	bwApply( s );
	if ( fly ) { fly.sync(); bwLookAt = fly.look; }
	if ( s.moving || look.yaw || look.pitch ) invalidate( 2 );
	bwTell();
	bwMapDraw();
	// out of the street door and on down the pavement: the street's own shot
	if ( s.surface !== 'street' ) bwBeenIn = true;
	else if ( bwOutside( s ) > ( bwBeenIn ? BW_OUT : BW_OUT_UNVISITED ) ) bwExit( 'street' );
	return true;
}
/* How far out of the building the body has walked from the door it is
 * nearest: the doorstep is a strip in front of each street door. */
function bwOutside( s ) {
	let best = - Infinity;
	for ( const p of ( lvPM && lvPM.portals ) || [] ) {
		const mx = ( p.a[ 0 ] + p.b[ 0 ] ) / 2, my = ( p.a[ 1 ] + p.b[ 1 ] ) / 2;
		const dx = s.pos.plan[ 0 ] - mx, dy = s.pos.plan[ 1 ] - my;
		if ( Math.hypot( dx, dy ) > 4 ) continue;
		best = Math.max( best, dx * p.normal[ 0 ] + dy * p.normal[ 1 ] );
	}
	return best;
}

/* The engine's state, on the screen. */
const _bwh = new THREE.Vector3(), _bwu = new THREE.Vector3();

/* ------------------------------------------------- the lifts' live parts
 * What cores.glb cannot carry because it changes as the car runs:
 *  - the CAR'S DOORS: a centre-opening pair on the shaft side of the car's
 *    front wall, riding with the car. Shut they stop 10 mm apart, so a rider
 *    sees the shaft, its landing doors and slab edges run past in the slit.
 *  - the DISPLAYS: the landing indicators over every landing door and the
 *    car's operating-panel display name the storey the car is at (the stop
 *    nearest it), with the direction of travel, and change as it passes.
 *  - the CALL LAMPS: the arrows on every landing's call station, a milky
 *    lens until the car is called there, then green until its doors part.
 * Placed off the geometry the build already has - the black glass each
 * display and button sits on (levels.js hands its vertices over) - so the
 * page never re-derives the lift kit's set-out. One mesh per material per
 * job, rebuilt only when what it shows changes. */
const LIFT_GLYPH = {
	'0': [ '111', '101', '101', '101', '111' ], '1': [ '010', '110', '010', '010', '111' ],
	'2': [ '111', '001', '111', '100', '111' ], '3': [ '111', '001', '111', '001', '111' ],
	'4': [ '101', '101', '111', '001', '001' ], '5': [ '111', '100', '111', '001', '111' ],
	'6': [ '111', '100', '111', '101', '111' ], '7': [ '111', '001', '010', '010', '010' ],
	'8': [ '111', '101', '111', '101', '111' ], '9': [ '111', '101', '111', '001', '111' ],
	'G': [ '111', '100', '101', '101', '111' ], 'O': [ '111', '101', '101', '101', '111' ],
	'P': [ '111', '101', '111', '100', '100' ], '-': [ '000', '000', '111', '000', '000' ],
	'^': [ '010', '111', '101', '000', '000' ], 'v': [ '000', '000', '101', '111', '010' ],
};
const liftLabel = ( id ) => id === 'L00' ? 'G' : id === 'L01' ? 'O' : id === 'P-1' ? '-1' : String( + id.slice( 1 ) - 1 );
// the stroke of a lift door: eased in and out, as an operator drives it
const liftEase = ( k ) => 0.5 - 0.5 * Math.cos( Math.PI * Math.max( 0, Math.min( 1, k ) ) );
const LIFT_DOOR_H = 2.10, LIFT_GAP = 0.010;

/* Boxes in the plan frame -> one non-indexed world geometry. A box is its
 * centre c (plan x, y), axes u and v (plan unit vectors), half sizes, and
 * a z range; every face is wound to face out whatever the frame's hand. */
function liftBoxes( boxes ) {
	const pos = [], nor = [];
	const W = ( x, y, z ) => frameP.world( x, y, z, new THREE.Vector3() );
	const _a = new THREE.Vector3(), _b = new THREE.Vector3(), _n = new THREE.Vector3();
	for ( const [ c, u, v, hu, hv, z0, z1 ] of boxes ) {
		const P = ( su, sv, z ) => W( c[ 0 ] + u[ 0 ] * su * hu + v[ 0 ] * sv * hv, c[ 1 ] + u[ 1 ] * su * hu + v[ 1 ] * sv * hv, z );
		const faces = [
			[ [ 1, - 1, z0 ], [ 1, 1, z0 ], [ 1, 1, z1 ], [ 1, - 1, z1 ], [ u, 0 ] ],
			[ [ - 1, 1, z0 ], [ - 1, - 1, z0 ], [ - 1, - 1, z1 ], [ - 1, 1, z1 ], [ u, 1 ] ],
			[ [ 1, 1, z0 ], [ - 1, 1, z0 ], [ - 1, 1, z1 ], [ 1, 1, z1 ], [ v, 0 ] ],
			[ [ - 1, - 1, z0 ], [ 1, - 1, z0 ], [ 1, - 1, z1 ], [ - 1, - 1, z1 ], [ v, 1 ] ],
			[ [ - 1, - 1, z1 ], [ 1, - 1, z1 ], [ 1, 1, z1 ], [ - 1, 1, z1 ], [ null, 0 ] ],
			[ [ - 1, 1, z0 ], [ 1, 1, z0 ], [ 1, - 1, z0 ], [ - 1, - 1, z0 ], [ null, 1 ] ],
		];
		for ( const [ p0, p1, p2, p3, [ ax, neg ] ] of faces ) {
			const q = [ p0, p1, p2, p3 ].map( ( p ) => P( p[ 0 ], p[ 1 ], p[ 2 ] ) );
			// the way this face looks, in the world
			if ( ax ) _n.copy( frameP.ex ).multiplyScalar( ax[ 0 ] ).addScaledVector( frameP.ey, ax[ 1 ] );
			else _n.copy( frameP.up );
			if ( neg ) _n.negate();
			_a.subVectors( q[ 1 ], q[ 0 ] ); _b.subVectors( q[ 2 ], q[ 0 ] );
			const flip = _a.cross( _b ).dot( _n ) < 0;
			const tri = flip ? [ 0, 2, 1, 0, 3, 2 ] : [ 0, 1, 2, 0, 2, 3 ];
			for ( const k of tri ) { pos.push( q[ k ].x, q[ k ].y, q[ k ].z ); nor.push( _n.x, _n.y, _n.z ); }
		}
	}
	const g = new THREE.BufferGeometry();
	g.setAttribute( 'position', new THREE.Float32BufferAttribute( pos, 3 ) );
	g.setAttribute( 'normal', new THREE.Float32BufferAttribute( nor, 3 ) );
	// the interiors' shaders read the owning flat's place: the lift is nobody's
	g.setAttribute( 'aunit', new THREE.Float32BufferAttribute( new Float32Array( pos.length / 3 ), 1 ) );
	g.computeBoundingSphere();
	return g;
}
/* Dot-matrix text centred on plan point c at height zc: `ur` runs to the
 * reader's right, `no` out of the glass towards them, dots from t0 to t1
 * along it (lib_plan `_dots`). */
function liftDots( out, text, c, ur, no, t0, t1, zc, px = 0.011, pitch = 0.014 ) {
	const w = text.length * 3 * pitch + ( text.length - 1 ) * pitch;
	let x = - w / 2 + pitch / 2;
	const tc = 0.5 * ( t0 + t1 );
	for ( const ch of text ) {
		const g = LIFT_GLYPH[ ch ];
		if ( g ) for ( let r = 0; r < 5; r ++ ) for ( let k = 0; k < 3; k ++ ) if ( g[ r ][ k ] === '1' ) {
			const s_ = x + k * pitch, z_ = zc + ( 2 - r ) * pitch;
			out.push( [ [ c[ 0 ] + ur[ 0 ] * s_ + no[ 0 ] * tc, c[ 1 ] + ur[ 1 ] * s_ + no[ 1 ] * tc ], ur, no,
				px / 2, ( t1 - t0 ) / 2, z_ - px / 2, z_ + px / 2 ] );
		}
		x += 4 * pitch;
	}
}
/* The plan-frame box of the vertices `pos` (world) whose height passes `keep`. */
function liftBox( pos, keep ) {
	const b = [ Infinity, Infinity, Infinity, - Infinity, - Infinity, - Infinity ];
	const v = new THREE.Vector3();
	for ( let i = 0; i < pos.length; i += 3 ) {
		v.set( pos[ i ], pos[ i + 1 ], pos[ i + 2 ] );
		const p = frameP.plan( v );
		if ( ! keep( p[ 2 ] ) ) continue;
		for ( let k = 0; k < 3; k ++ ) { b[ k ] = Math.min( b[ k ], p[ k ] ); b[ k + 3 ] = Math.max( b[ k + 3 ], p[ k ] ); }
	}
	return b[ 0 ] === Infinity ? null : b;
}

function liftKit( group, geo, pm ) {
	const kits = new Map();
	if ( ! geo || ! pm || ! frameP ) return kits;
	const mk = ( mat, name ) => {
		const m = new THREE.Mesh( new THREE.BufferGeometry(), lvMat( mat ) );
		m.name = name; m.matrixAutoUpdate = false; m.frustumCulled = false;
		m.castShadow = false; m.receiveShadow = true;
		m.visible = false;
		group.add( m );
		return m;
	};
	for ( const rec of pm.lifts || [] ) {
		const id = rec.core + '-' + rec.shaft;
		const cab = LVL.ringOf( rec.cab );
		const xs = cab.map( p => p[ 0 ] ), ys = cab.map( p => p[ 1 ] );
		const bx0 = Math.min( ...xs ), bx1 = Math.max( ...xs ), by0 = Math.min( ...ys ), by1 = Math.max( ...ys );
		const cx = ( bx0 + bx1 ) / 2, cy = ( by0 + by1 ) / 2;
		const rest = ( rec.stops.find( x => x.level === rec.car_at ) || rec.stops[ 0 ] ).z;
		const seg = ( rec.stops.find( x => x.door ) || {} ).door;
		if ( ! seg ) continue;
		const [ a, b ] = seg;
		// the car's front: the side its landing doors are on (lib_plan `lift_car`)
		const alongY = Math.abs( a[ 0 ] - b[ 0 ] ) < 1e-3;
		const v = alongY ? [ a[ 0 ] > cx ? 1 : - 1, 0 ] : [ 0, a[ 1 ] > cy ? 1 : - 1 ];   // out of the car
		const u = alongY ? [ 0, 1 ] : [ 1, 0 ];
		const o0 = Math.min( alongY ? a[ 1 ] : a[ 0 ], alongY ? b[ 1 ] : b[ 0 ] ), o1 = Math.max( alongY ? a[ 1 ] : a[ 0 ], alongY ? b[ 1 ] : b[ 0 ] );
		const hw = ( o1 - o0 ) / 2 - 0.05, mid = ( o0 + o1 ) / 2;
		const face = alongY ? ( v[ 0 ] > 0 ? bx1 : bx0 ) : ( v[ 1 ] > 0 ? by1 : by0 );
		// each leaf: from the slit to 25 mm behind the jamb, 12..34 mm out of the car's front
		const leafW = hw + 0.025 - LIFT_GAP / 2, dOut = face * ( alongY ? v[ 0 ] : v[ 1 ] ) + 0.023;
		const leaf = ( sg ) => {
			const cu = mid + sg * ( LIFT_GAP / 2 + leafW / 2 );
			const c = alongY ? [ dOut * v[ 0 ], cu ] : [ cu, dOut * v[ 1 ] ];
			// a skin and a raised panel on each face, as the landing leaves
			return liftBoxes( [ [ c, u, v, leafW / 2, 0.011, rest, rest + LIFT_DOOR_H + 0.02 ],
				[ [ c[ 0 ] - v[ 0 ] * 0.0125, c[ 1 ] - v[ 1 ] * 0.0125 ], u, v, leafW / 2 - 0.045, 0.0015, rest + 0.10, rest + LIFT_DOOR_H - 0.08 ] ] );
		};
		const K = { id, rest, u, hw, doors: [], text: null, called: undefined, off: 0, k: - 1 };
		for ( const sg of [ - 1, 1 ] ) {
			const m = mk( 'chrome', 'lift_' + id + '_cardoor' + ( sg < 0 ? 'L' : 'R' ) );
			m.material = lvMat( 'lift_chrome' ) || m.material;
			m.geometry = leaf( sg ); m.userData.sg = sg;
			m.castShadow = true;
			K.doors.push( m );
		}
		// the car's display (its operating panel) and the arrow strip over its door
		const cpos = geo.car.get( rec.car_node );
		const disp = cpos && liftBox( cpos, ( z ) => z > rest + 1.49 && z < rest + 1.60 );
		const strip = cpos && liftBox( cpos, ( z ) => z > rest + 2.14 && z < rest + 2.22 );
		const inward = [ - v[ 0 ], - v[ 1 ] ];
		K.carAt = [];
		for ( const bb of [ disp, strip ] ) {
			if ( ! bb ) { K.carAt.push( null ); continue; }
			const c = [ ( bb[ 0 ] + bb[ 3 ] ) / 2, ( bb[ 1 ] + bb[ 4 ] ) / 2 ];
			// the glass's face towards the car's middle
			const f = alongY ? ( inward[ 0 ] > 0 ? bb[ 3 ] : bb[ 0 ] ) : ( inward[ 1 ] > 0 ? bb[ 4 ] : bb[ 1 ] );
			const c0 = alongY ? [ f, c[ 1 ] ] : [ c[ 0 ], f ];
			K.carAt.push( { c: c0, z: ( bb[ 2 ] + bb[ 5 ] ) / 2, ur: [ - v[ 1 ], v[ 0 ] ], no: inward } );
		}
		K.carLed = mk( 'neon_orange', 'lift_' + id + '_carled' );
		// the landings: an indicator over each door, a call station beside it
		K.land = [];
		for ( const st of rec.stops ) {
			if ( ! st.door ) continue;
			const pos = geo.ind.get( `in_${ rec.core }_lift${ rec.shaft }_${ st.level }_ind__int_black` );
			if ( ! pos ) continue;
			const [ p, q ] = st.door, mx = ( p[ 0 ] + q[ 0 ] ) / 2, my = ( p[ 1 ] + q[ 1 ] ) / 2;
			const no = [ v[ 0 ], v[ 1 ] ];                                   // into the lobby
			const ur = [ no[ 1 ], - no[ 0 ] ];                               // lib_plan: r = (-f.y, f.x), f = -no
			const ib = liftBox( pos, ( z ) => z > st.z + 1.8 );
			const frontOf = ( bb ) => alongY ? ( no[ 0 ] > 0 ? bb[ 3 ] : bb[ 0 ] ) : ( no[ 1 ] > 0 ? bb[ 4 ] : bb[ 1 ] );
			const at = ( bb, f ) => alongY ? [ f, ( bb[ 1 ] + bb[ 4 ] ) / 2 ] : [ ( bb[ 0 ] + bb[ 3 ] ) / 2, f ];
			const k_ = rec.stops.indexOf( st );
			// the walk calls a car without asking where the visitor is going:
			// the lamp that lights is the way most of the building lies
			const way = k_ < ( rec.stops.length - 1 ) / 2 ? 1 : - 1;
			const L = { level: st.level, way, ind: ib ? { c: at( ib, frontOf( ib ) ), z: ( ib[ 2 ] + ib[ 5 ] ) / 2 } : null, btn: [], no, ur, mid: [ mx, my ] };
			// the call buttons: the black squares low on the wall, top to bottom
			const lows = [];
			for ( let i = 0; i < pos.length; i += 3 ) {
				const w = frameP.plan( _bwh.set( pos[ i ], pos[ i + 1 ], pos[ i + 2 ] ) );
				if ( w[ 2 ] > st.z + 0.9 && w[ 2 ] < st.z + 1.3 ) lows.push( w );
			}
			// top to bottom; a button is 38 mm tall and the next is 62 mm under it
			lows.sort( ( m, n ) => n[ 2 ] - m[ 2 ] );
			const groups = [];
			for ( const w of lows ) {
				const g = groups[ groups.length - 1 ];
				if ( g && g.lo - w[ 2 ] < 0.05 ) { g.pts.push( w ); g.lo = w[ 2 ]; } else groups.push( { lo: w[ 2 ], pts: [ w ] } );
			}
			const first = st.level === rec.stops[ 0 ].level, last = st.level === rec.stops[ rec.stops.length - 1 ].level;
			groups.forEach( ( G, k ) => {
				const bb = [ Infinity, Infinity, Infinity, - Infinity, - Infinity, - Infinity ];
				for ( const w of G.pts ) for ( let j = 0; j < 3; j ++ ) { bb[ j ] = Math.min( bb[ j ], w[ j ] ); bb[ j + 3 ] = Math.max( bb[ j + 3 ], w[ j ] ); }
				const arrow = groups.length === 2 ? ( k === 0 ? '^' : 'v' ) : ( first ? '^' : last ? 'v' : '^' );
				L.btn.push( { c: at( bb, frontOf( bb ) ), z: ( bb[ 2 ] + bb[ 5 ] ) / 2, arrow, way: arrow === '^' ? 1 : - 1 } );
			} );
			K.land.push( L );
		}
		K.landLed = mk( 'neon_orange', 'lift_' + id + '_landled' );
		K.lampOn = mk( 'lift_green', 'lift_' + id + '_lampon' );
		K.lampOff = mk( 'lift_lamp_off', 'lift_' + id + '_lampoff' );
		kits.set( id, K );
	}
	// the first frame shows something on every mesh, so the gate compiles them all
	for ( const K of kits.values() ) liftKitSet( K, { z: K.rest, doorOpen: 0, shows: 'L00', dir: 0, called: null }, 0, true );
	return kits;
}
const _lkm = new THREE.Matrix4();
/* One lift's live parts to the walk's state `l`; `off` is the car's rise
 * over its rest. Returns true if anything was rebuilt. */
function liftKitSet( K, l, off, warm = false ) {
	if ( ! K ) return false;
	let changed = false;
	const k = liftEase( l.doorOpen || 0 );
	if ( off !== K.off || k !== K.k ) {
		K.off = off; K.k = k;
		for ( const m of K.doors ) {
			const s = m.userData.sg * ( K.hw + 0.012 ) * k;
			_bwu.copy( frameP.up ).multiplyScalar( off )
				.addScaledVector( frameP.ex, K.u[ 0 ] * s ).addScaledVector( frameP.ey, K.u[ 1 ] * s );
			m.matrix.makeTranslation( _bwu.x, _bwu.y, _bwu.z );
			m.matrixWorldNeedsUpdate = true;
			m.visible = true;
		}
		_bwu.copy( frameP.up ).multiplyScalar( off );
		K.carLed.matrix.makeTranslation( _bwu.x, _bwu.y, _bwu.z );
		K.carLed.matrixWorldNeedsUpdate = true;
	}
	// what the displays say: the storey, and the way the car is going
	const arrow = l.dir > 0 ? '^' : l.dir < 0 ? 'v' : '';
	const lab = liftLabel( l.shows || 'L00' );
	const text = arrow + lab;
	if ( text !== K.text || warm ) {
		K.text = text;
		const car = [], land = [];
		const [ D, S ] = K.carAt;
		if ( D ) liftDots( car, text, D.c, D.ur, D.no, 0.0005, 0.002, D.z, 0.008, 0.010 );
		if ( S && arrow ) liftDots( car, arrow, S.c, S.ur, S.no, 0.0005, 0.002, S.z, 0.007, 0.009 );
		for ( const L of K.land ) if ( L.ind ) liftDots( land, text, L.ind.c, L.ur, L.no, 0.0005, 0.002, L.ind.z );
		for ( const [ m, boxes ] of [ [ K.carLed, car ], [ K.landLed, land ] ] ) {
			m.geometry.dispose();
			m.geometry = boxes.length ? liftBoxes( boxes ) : new THREE.BufferGeometry();
			m.visible = boxes.length > 0;
		}
		changed = true;
	}
	const called = l.called || null;
	if ( called !== K.called || warm ) {
		K.called = called;
		const on = [], offB = [];
		for ( const L of K.land ) for ( const B of L.btn )
			liftDots( L.level === called && ( B.way === L.way || L.btn.length === 1 ) ? on : offB, B.arrow, B.c, L.ur, L.no, 0.0005, 0.002, B.z, 0.006, 0.008 );
		// a warm-up lights one lamp, so the green's pipeline is built with the rest
		if ( warm && ! on.length && offB.length ) on.push( offB[ 0 ] );
		for ( const [ m, boxes ] of [ [ K.lampOn, on ], [ K.lampOff, offB ] ] ) {
			m.geometry.dispose();
			m.geometry = boxes.length ? liftBoxes( boxes ) : new THREE.BufferGeometry();
			m.visible = boxes.length > 0;
		}
		if ( warm ) K.called = undefined;
		changed = true;
	}
	return changed;
}

function bwApply( s, place = true ) {
	if ( ! s ) return;
	/* What has to be here: what the engine needs - but a car between
	 * storeys needs only where it is going (its doors are shut on every
	 * storey it passes). */
	/* A car going past a storey needs its walls (the shaft is theirs) but
	 * not its furniture; where it is going, both. */
	const riding = !! ( s.inLift && s.inLift.riding );
	const want = s.needLevels;
	if ( riding ) { bwWant( want, false ); bwWant( [ s.inLift.to ] ); } else bwWant( want );
	/* Ahead of the visitor: in a car, the storeys either side of it (the
	 * likeliest stops) - walls and furniture, so a first arrival's compile
	 * happens while the doors are still open here, not on arrival there. A
	 * flight is already covered: `needLevels` holds both of its ends. */
	if ( s.inLift && /^L\d\d$/.test( s.level ) && ( RIDE_AHEAD_OLD || ! riding ) && ! bwAhead.has( s.inLift.id + s.level ) ) {
		bwAhead.add( s.inLift.id + s.level );
		const k = lvStorey( s.level );
		bwWant( [ lvOfStorey( k + 1 ), lvOfStorey( k - 1 ) ].filter( id => id && lvMetaLevel( id ) && id !== s.level ) );
	}
	if ( ! s.inLift ) bwAhead.clear();
	const show = new Set( want.filter( id => bwHere( id, riding && id !== s.inLift.to ? 'shaft' : null ) ) );
	if ( bwHere( s.level ) ) show.add( s.level );
	let changed = false;
	for ( const P of lvParts.values() ) {
		if ( P.name === 'cores' || P.state !== 'in' || P.warming ) continue;   // warming: see `lvWarmWalk`
		const on = show.has( P.name );
		if ( P.group.visible !== on ) { lvShow( P.name, on ); changed = true; }
		if ( P.cap && P.cap.visible ) P.cap.visible = false;
		if ( on && P.furn && P.furnAll !== 1 ) { P.furn.walk( true ); P.furnAll = 1; changed = true; }
	}
	const C = lvParts.get( 'cores' );
	if ( C && C.group && ! C.group.visible && C.state === 'in' ) { C.group.visible = true; changed = true; }
	bwShown = show;
	// the street's loggia panes of the storeys on screen: the interior's own leaves glaze the doors
	if ( lgSplit( show ) ) changed = true;
	// the street's stand-in door leaves go once the hall's own are on screen
	bwStreetLeafSet( ! show.has( 'L00' ) );
	// ...and the leaves the engine has open
	const seen = new Set();
	for ( const d of s.doors ) {
		const P = lvParts.get( d.level );
		if ( ! P || ! P.movers || ! show.has( d.level ) ) continue;
		const N = P.movers.nodes.get( d.node );
		if ( ! N || ! N.door ) continue;
		const h = N.door.hinge, L = lvLevel( d.level );
		frameP.world( h[ 0 ], h[ 1 ], L ? L.z : 0, _bwh );
		const a = - ( d.angle - N.door.shut ) * Math.PI / 180;
		_bwm.makeTranslation( _bwh.x, _bwh.y, _bwh.z )
			.multiply( new THREE.Matrix4().makeRotationAxis( frameP.up, a ) )
			.multiply( new THREE.Matrix4().makeTranslation( - _bwh.x, - _bwh.y, - _bwh.z ) );
		P.movers.set( d.node, _bwm );
		seen.add( d.node ); bwOut.set( d.node, d.level );
	}
	for ( const [ node, lv ] of bwOut ) if ( ! seen.has( node ) ) {
		const P = lvParts.get( lv );
		if ( P && P.movers ) P.movers.set( node, null );
		bwOut.delete( node );
		changed = true;
	}
	// the cars, and the landing doors they open
	if ( C && C.movers && lvPM ) {
		for ( const l of s.lifts ) {
			const rec = ( lvPM.lifts || [] ).find( x => x.core + '-' + x.shaft === l.id );
			if ( ! rec ) continue;
			const rest = ( rec.stops.find( x => x.level === rec.car_at ) || rec.stops[ 0 ] ).z;
			_bwu.copy( frameP.up ).multiplyScalar( l.z - rest );
			C.movers.set( l.car, _bwm.makeTranslation( _bwu.x, _bwu.y, _bwu.z ) );
			if ( C.lifts && liftKitSet( C.lifts.get( l.id ), l, l.z - rest ) ) changed = true;
			for ( const st of rec.stops ) {
				/* Two leaves that part in the middle, each sliding its own
				 * width into the wall beside the opening - on the same
				 * eased stroke as the car's own pair (`liftKitSet`). */
				const k = l.level === st.level ? liftEase( l.doorOpen ) : 0;
				const dx = ( st.door[ 1 ][ 0 ] - st.door[ 0 ][ 0 ] ) * 0.48 * k, dy = ( st.door[ 1 ][ 1 ] - st.door[ 0 ][ 1 ] ) * 0.48 * k;
				for ( const [ leaf, sg ] of [ [ 'door', - 1 ], [ 'door2', 1 ] ] ) {
					const node = `in_${ rec.core }_lift${ rec.shaft }_${ st.level }_${ leaf }__chrome`;
					if ( k <= 0 ) { if ( C.movers.out.has( node ) ) { C.movers.set( node, null ); changed = true; } continue; }
					_bwu.copy( frameP.ex ).multiplyScalar( dx * sg ).addScaledVector( frameP.ey, dy * sg );
					C.movers.set( node, _bwm.makeTranslation( _bwu.x, _bwu.y, _bwu.z ) );
				}
			}
		}
	}
	for ( const P of lvParts.values() ) if ( P.movers && P.movers.flush() ) changed = true;
	/* The sun's map is drawn again when something that casts has MOVED -
	 * a leaf turning, a car, its doors - and not merely because a door is
	 * standing open: the map is the most expensive thing on the page. */
	let sig = '';
	for ( const d of s.doors ) sig += d.node + ( d.angle * 4 | 0 ) + ';';
	for ( const l of s.lifts ) sig += ( l.z * 100 | 0 ) + ':' + ( l.doorOpen * 50 | 0 ) + ';';
	if ( sig !== bwSig ) { bwSig = sig; shadowDirty(); }
	if ( changed ) { shadowDirty(); invalidate( 2 ); }
	// the sun, fitted to where the body is, and the light of where it stands
	bwShadow( s.flat || s.office ? BW_SHADOW_FLAT : BW_SHADOW_COMMON );
	bwLightAim( s );
	if ( place ) bwPlace( s );
}

function bwShadow( far ) {
	if ( ! sun || ! sun.shadow.camera || ROOM_SHADOW <= 0 ) return;
	if ( far === bwShadowFar && roomShadowOn ) return;
	bwShadowFar = far;
	roomShadowOn = true;
	sun.shadow.camera.far = far;
	shadowDirty();
}

/* Does the interior hang its own leaf in EVERY street door that has a
 * stand-in? scene_meta.site.entrances[] says which street leaves a door has
 * (`street_leaf`) and what the build thought of the interior
 * (`interior_leaf`); plan_meta's portals say what the interior actually
 * carries (`nodes`), and either is enough - since build 3 C3 (a made double
 * door) and the terrace stair's door have leaves of their own as well as C1
 * and C2. The street's stand-ins are one welded group, so they go together:
 * only when no doorway would be left standing open without a leaf. */
let bwLeafCover = null;
function bwStreetLeafCovered() {
	if ( bwLeafCover !== null ) return bwLeafCover;
	const ents = ( meta && meta.site && meta.site.entrances ) || [];
	const portals = ( lvPM && lvPM.portals ) || [];
	if ( ! lvPM ) return true;               // the old rule until plan_meta is in
	const bare = ents.filter( e => ( e.street_leaf || [] ).length && ! e.interior_leaf
		&& ! portals.some( p => ( p.core || p.id ) === e.id && ( ( p.nodes && p.nodes.length ) || p.node ) ) );
	if ( bare.length ) console.info( 'walk: street doors with no interior leaf, stand-ins kept:', bare.map( e => e.id ) );
	return ( bwLeafCover = ! bare.length );
}
/* The street's own door leaves - stand-ins drawn shut, which the hall's leaf
 * replaces once the hall is on screen (CONTRACT "Street doors"). They were
 * set aside into their own group by `groupOf` so they can be hidden. */
function bwStreetLeafSet( on ) {
	if ( ! on && ! bwStreetLeafCovered() ) on = true;
	if ( ! groups.leaf || groups.leaf.visible === on ) return;
	groups.leaf.visible = on;
	shadowDirty();
	invalidate( 2 );
}

/* ------------------------------------------------- the light indoors
 * The street is lit for the street: a sky PMREM at 1.45 that every surface
 * sees whole, a cold hemisphere, an exposure set for a sunlit facade. Under a
 * ceiling none of that is true - the sky comes in through a window or two
 * and most of what lights a room is that light again, off a white ceiling
 * and a warm floor - and the street's set-up laid over a room reads as a
 * grey-navy wash with no direction in it (perf-shots/tourcheck, build 3).
 *
 * So a visitor under a ceiling gets a room's light: the sky's share cut back
 * (`env`), the hemisphere turned into the bounce - warm white from above,
 * parquet from below - and an eye that has adapted to indoors (`exp`), with
 * the lens' vignette eased off. Corridors, halls and stairs have no windows
 * at all, so their fill is a little stronger (`common`). Nothing is added or
 * taken away - the same light, the same uniforms, different values - so no
 * pipeline is built for it and the street, where `t` is 0, is the street to
 * the bit. It eases over ~0.6 s on the frame loop (`bwLightStep`), so a step
 * in from a loggia or the street is an eye adjusting, not a switch.
 * `?inlight=env,hemi,exp,common` tunes it; `?inlight=0` keeps the street's. */
const BW_LIGHT = ( () => {
	const q = ( __q.get( 'inlight' ) || '' ).split( ',' ).map( Number );
	const v = ( i, d ) => Number.isFinite( q[ i ] ) && q[ i ] > 0 ? q[ i ] : d;
	return { off: __q.get( 'inlight' ) === '0',
		env: v( 0, 0.6 ), hemi: v( 1, 2.0 ), exp: v( 2, 1.16 ), common: v( 3, 1.4 ),
		sky: new THREE.Color( __q.get( 'insky' ) || 0xfffaf2 ), ground: new THREE.Color( __q.get( 'inground' ) || 0xdcc6aa ), vign: 0.35 };
} )();
let bwLightT = 0, bwLightGoal = 0, bwLightK = 1, bwLightOut = null;
const _bwc = new THREE.Color();
/* Is the body under a ceiling, and in a room with windows (1) or a corridor,
 * a hall, a stair or a car (BW_LIGHT.common)? */
function bwLightAim( s ) {
	if ( ! s || BW_LIGHT.off ) { bwLightGoal = 0; return; }
	const out = s.surface === 'street' || s.surface === 'terrace' || s.surface === 'loggia'
		|| ( s.room && s.room.kind === 'loggia' );
	bwLightGoal = out ? 0 : 1;
	if ( ! out ) bwLightK = s.flat || s.office ? 1 : BW_LIGHT.common;
}
function bwLightSet( t ) {
	if ( ! hemi || ! sun ) return;
	if ( ! bwLightOut ) bwLightOut = { env: scene.environmentIntensity, hemi: hemi.intensity,
		sky: hemi.color.clone(), ground: hemi.groundColor.clone(), exp: renderer.toneMappingExposure };
	const O = bwLightOut;
	if ( t <= 0 ) {
		// the street's own values, as they were - not a lerp that lands near them
		scene.environmentIntensity = O.env; hemi.intensity = O.hemi;
		hemi.color.copy( O.sky ); hemi.groundColor.copy( O.ground );
		renderer.toneMappingExposure = O.exp; vignAmount.value = 1.0;
		return;
	}
	const L = BW_LIGHT;
	scene.environmentIntensity = O.env + ( L.env - O.env ) * t;
	hemi.intensity = O.hemi + ( L.hemi * bwLightK - O.hemi ) * t;
	hemi.color.copy( O.sky ).lerp( _bwc.copy( L.sky ), t );
	hemi.groundColor.copy( O.ground ).lerp( _bwc.copy( L.ground ), t );
	renderer.toneMappingExposure = O.exp + ( L.exp - O.exp ) * t;
	vignAmount.value = 1 - ( 1 - L.vign ) * t;
}
/* On the frame loop: true while it is still easing (a frame is owed). */
function bwLightStep( dt ) {
	if ( ! bwOn ) bwLightGoal = 0;
	if ( bwLightT === bwLightGoal ) return false;
	const k = dt / 0.6;
	bwLightT = bwLightGoal > bwLightT ? Math.min( bwLightGoal, bwLightT + k ) : Math.max( bwLightGoal, bwLightT - k );
	bwLightSet( bwLightT );
	return true;
}
window.__bwLight = () => ( { t: bwLightT, goal: bwLightGoal, k: bwLightK, env: scene && scene.environmentIntensity,
	hemi: hemi && hemi.intensity, exp: renderer && renderer.toneMappingExposure, vign: vignAmount.value } );

/* ------------------------------------------------- the way out */
function bwExit( to = null ) {
	if ( ! bwOn ) return false;
	const s = bwS;
	bwOn = false;
	embedCursor( false );
	bwAsk ++;
	bwEnded = performance.now();
	bwTouch = null;
	camera.near = 0.25;
	camera.updateProjectionMatrix();
	roomShadowOn = false;
	if ( sun && sun.shadow.camera ) sun.shadow.camera.far = SHADOW_FAR;
	bwShadowFar = 0;
	// every leaf and car back where the welds have them
	for ( const P of lvParts.values() ) if ( P.movers ) {
		for ( const n of [ ...P.movers.out.keys() ] ) if ( P.name !== 'cores' || ! LVL.LIFT_CAR.test( n ) ) P.movers.set( n, null );
		P.movers.flush();
	}
	bwOut.clear();
	bwStreetLeafSet( true );
	// the section caps, which the walk took off every level it showed, and the loggia panes
	for ( const P of lvParts.values() ) if ( P.cap ) P.cap.visible = true;
	lgSplit( null );
	const level = s && s.level && /^L\d\d$/.test( s.level ) ? s.level : null;
	const goStreet = to === 'street' || ! level || level === 'L00' || ( ! to && bwFrom === 'street' && level === 'L00' );
	bwTell( true );
	/* 'none': whoever called is about to put the scene somewhere itself (a
	 * level opened, the street asked for) - only the walk is undone. */
	if ( to === 'none' ) {
		scene2View = 'plan';
		lvInside = true;            // so the next `lvInsideSet( false )` puts the cut and the caps back
		for ( const id of bwShown ) lvShow( id, false );
		bwShown.clear();
		lvOpen = null;
		return true;
	}
	if ( goStreet ) {
		/* Back to the street: the levels go away behind the camera once it
		 * is out - not before, or the first frames of the flight would be
		 * a hall with nothing in it. */
		lvInside = false;
		lvOpen = level || lvOpen;
		scene2View = 'plan';
		const gone = [ ...bwShown ].filter( id => id !== lvOpen );
		bwShown.clear();
		// the camera leaves through full-height rooms: no ink slab at 1.45 m in them
		const P0 = lvParts.get( lvOpen );
		if ( P0 && P0.cap ) P0.cap.visible = false;
		lvLeave( true );
		setTimeout( () => { if ( ! bwOn && sceneNo === 1 ) for ( const id of gone ) lvShow( id, false ); }, FLOOR_IN + 100 );
		return true;
	}
	/* Back up to the floor view of the storey the body is on, with the flat it
	 * is standing in open. */
	for ( const id of bwShown ) if ( id !== level ) lvShow( id, false );
	bwShown.clear();
	for ( const P of lvParts.values() ) if ( P.furn ) { P.furnAll = 0; lvFurnSync( P ); }
	scene2View = 'plan';
	lvInside = true;            // `lvEnter`'s `lvInsideSet( false )` then puts the cut and its caps back
	const n = s.flat || null;
	lvOpen = level;
	sceneNo = 2;
	lvEnterFromWalk( level, n );
	return true;
}
/* `lvEnter` with the camera coming UP out of the building rather than
 * across from the street: the cut comes back at once and the camera rises
 * to the plan (or to the flat, if the body was standing in one). */
function lvEnterFromWalk( id, n ) {
	const L = lvLevel( id );
	if ( ! L ) return;
	lvOpen = null;               // so `lvEnter` does not take it for the open level
	sceneNo = 2;
	lvEnter( id, n );
}

/* ------------------------------------------------- the street's doors
 * The three entrance doors and the terrace stair's, as hit quads where
 * scene_meta says the doors are: a pointer over one says so, a click walks
 * up to it. */
function bwBuildDoors() {
	const E = meta && meta.site && meta.site.entrances;
	if ( ! E || ! frameP ) return;
	const pickMat = new THREE.MeshBasicMaterial( { side: THREE.DoubleSide } );
	bwPick = new THREE.Group();
	bwPick.name = 'door_pick';
	for ( const e of E ) {
		/* Only doors a walk can begin at: the entrances and the terrace stair.
		 * The shop doors (`kind: 'commercial'`, model build 4) have no portal
		 * in plan_meta and no number to name them by. */
		if ( e.kind === 'commercial' || ( e.kind == null && ! /^(C\d|podium)$/.test( e.id ) ) ) continue;
		const w = ( e.w || 1 ) + 0.6, h = ( e.h || 2.1 ) + 0.3;
		const a = Math.atan2( e.out[ 1 ], e.out[ 0 ] );
		const t = [ - Math.sin( a ), Math.cos( a ) ];          // along the door
		const c = frameP.world( e.door[ 0 ] + e.out[ 0 ] * 0.15, e.door[ 1 ] + e.out[ 1 ] * 0.15, ( e.z || 0 ) + h / 2 );
		const u = frameP.world( t[ 0 ], t[ 1 ], 0 ).sub( frameP.world( 0, 0, 0 ) ).normalize();
		const g = new THREE.PlaneGeometry( w, h );
		g.applyMatrix4( new THREE.Matrix4().makeBasis( u, frameP.up, new THREE.Vector3().crossVectors( u, frameP.up ) ).setPosition( c ) );
		const m = new THREE.Mesh( g, pickMat );
		m.visible = false;
		m.userData.portal = e.id;
		bwPick.add( m );
	}
	scene.add( bwPick );
}
function bwDoorUnder( px ) {
	if ( ! px || ! bwPick ) return null;
	const r = renderer.domElement.getBoundingClientRect();
	_fndc.set( ( px[ 0 ] - r.left ) / r.width * 2 - 1, - ( ( px[ 1 ] - r.top ) / r.height ) * 2 + 1 );
	_fray.setFromCamera( _fndc, camera );
	const hit = _fray.intersectObjects( bwPick.children, false )[ 0 ];
	if ( ! hit ) return null;
	/* ...and only if nothing of the street stands in front of it (a tree, a
	 * parasol): the door has to be what the pointer is on. */
	const solid = _fray.intersectObjects( [ groups.main, groups.tower ].filter( Boolean ), true )
		.find( h => h.object.isMesh && h.object.visible );
	if ( solid && solid.distance < hit.distance - 0.6 ) return null;
	return hit.object.userData.portal;
}
function bwHotSet( id ) {
	if ( id === bwHot ) return;
	if ( id && FLAT_GONE ) lvPrewarm();    // intent: a door you could walk in by
	bwHot = id;
	const k = id ? ( /^C(\d)$/.exec( id ) || [] )[ 1 ] : null;
	announce( 'door', { portal: id, k: k ? + k : null, terrace: id === 'podium' } );
	embedCursor( false );
	invalidate( 2 );
}

/* ------------------------------------------------- what the page is told
 * `lp:walk` - on/off, the storey (and the residential floor 1..9), the flat
 * or office, the room with its Georgian name, the lift's stops - only when
 * one of them changes. The page draws the HUD and the lift's buttons. */
function bwTell( force = false ) {
	const s = bwS;
	let d;
	if ( ! bwOn || ! s ) d = { on: false };
	else {
		const ml = lvMetaLevel( s.level );
		let room = null;
		if ( s.room ) {
			room = { name: s.room.name, kind: s.room.kind, ka: null };
			const L = lvLevel( s.level );
			const u = L && L.units.find( x => ( s.flat != null && ! x.office && String( x.n ) === String( s.flat ) )
				|| ( s.office != null && x.office && String( x.n ) === String( s.office ) ) );
			const R = u && ( u.rooms || [] )[ s.room.i ];
			if ( R ) { const lite = lvLite && lvLite[ u.key ]; const q = lite && R.rooms_id ? lite[ R.rooms_id ] : null;
				room.ka = R.name_ka || ( q && q[ 8 ] ) || null;
				// the sheets' unnamed rooms: "Room N" (levels.js `roomNumber`)
				const nm = ! R.name && LVL.roomNumber( u, s.room.i );
				if ( nm ) { room.name = nm.name; room.ka = room.ka || nm.ka; } }
		}
		d = { on: true, level: s.level, floor: ml && ml.res ? ml.res : 0, floors: ( meta.levels || [] ).filter( l => l.res ).length,
			flat: s.flat, office: s.office, room, surface: s.surface, onStair: s.onStair,
			lift: s.inLift ? { id: s.inLift.id, stops: s.inLift.stops, at: s.inLift.at, to: s.inLift.to, riding: s.inLift.riding } : null,
			from: bwFrom, waiting: ! bwAllReady( ( s.seesLevels || s.needLevels ).filter( id => id !== 'ROOF' ) )
				|| ( compiling && compileSince > 0 && performance.now() - compileSince > BW_HOLD_CUE ) };
	}
	const key = JSON.stringify( d );
	if ( ! force && key === bwSaid ) return;
	bwSaid = key;
	announce( 'walk', d );
}

/* The minimap: the storey's own floors from plan_meta, the flat the body is
 * in picked out, and a dot with the way it is facing - drawn into a canvas
 * the page hands over (`LP.walkMap = canvas`). The street side at the foot,
 * as the floor view and the architect's sheets have it. */
function bwMapDraw( force = false ) {
	const c = bwMapEl, s = bwS;
	if ( ! c || ! s || ! bwW || ! bwOn ) return;
	const N = bwW.nav( s.level );
	if ( ! N ) return;
	const key = s.level + '|' + ( s.flat || s.office || '' ) + '|' + c.width + 'x' + c.height;
	let M = bwMapCache.get( key );
	if ( ! M ) {
		const bb = N.bb, W = c.width, H = c.height;
		const sc = Math.min( ( W - 8 ) / ( bb[ 2 ] - bb[ 0 ] ), ( H - 8 ) / ( bb[ 3 ] - bb[ 1 ] ) );
		const ox = ( W - ( bb[ 2 ] - bb[ 0 ] ) * sc ) / 2, oy = ( H - ( bb[ 3 ] - bb[ 1 ] ) * sc ) / 2;
		const P = ( x, y ) => [ ox + ( x - bb[ 0 ] ) * sc, oy + ( y - bb[ 1 ] ) * sc ];
		const off = document.createElement( 'canvas' ); off.width = W; off.height = H;
		const g = off.getContext( '2d' );
		const fillP = ( rings, col ) => {
			g.fillStyle = col; g.beginPath();
			for ( const r of rings ) { for ( let i = 0; i < r.length; i += 2 ) { const [ px, py ] = P( r[ i ], r[ i + 1 ] ); i ? g.lineTo( px, py ) : g.moveTo( px, py ); } g.closePath(); }
			g.fill( 'evenodd' );
		};
		const col = { flat: '#e5af69', loggia: '#f0cf9f', corridor: '#f3ede2', hall: '#f3ede2', door: '#f3ede2',
			half_landing: '#d8d2c6', stair: '#d8d2c6', terrace: '#cfe0c4', commercial: '#e9e4da', street: '#cfcac0',
			head: '#d8d2c6', lift: '#9aa3ad', sill: '#9aa3ad' };
		for ( const sf of N.surf ) fillP( sf.P.rings, col[ sf.kind ] || '#ddd' );
		const mine = N.units.find( u => String( u.n ) === String( s.flat != null ? s.flat : s.office ) && !! u.office === ( s.flat == null ) );
		if ( mine ) fillP( mine.P.rings, '#1d3559' );
		M = { off, P, sc };
		bwMapCache.set( key, M );
		if ( bwMapCache.size > 24 ) bwMapCache.delete( bwMapCache.keys().next().value );
	}
	const g = c.getContext( '2d' );
	g.clearRect( 0, 0, c.width, c.height );
	g.drawImage( M.off, 0, 0 );
	const [ px, py ] = M.P( s.pos.plan[ 0 ], s.pos.plan[ 1 ] );
	g.fillStyle = '#c8102e'; g.strokeStyle = '#c8102e'; g.lineWidth = 2;
	g.beginPath(); g.arc( px, py, 4, 0, 7 ); g.fill();
	g.beginPath(); g.moveTo( px, py ); g.lineTo( px + Math.cos( s.heading ) * 13, py + Math.sin( s.heading ) * 13 ); g.stroke();
}

/* A thumb on the left half of the window walks (a stick: up is forward),
 * one on the right half looks - the fly controls' drag. Taken before the fly
 * controls see the event, and only while walking. */
function bwTouchWire( dom ) {
	dom.addEventListener( 'pointerdown', ( e ) => {
		if ( ! bwOn || e.pointerType !== 'touch' || e.clientX > innerWidth / 2 ) return;
		bwTouch = { id: e.pointerId, x: e.clientX, y: e.clientY, f: 0, r: 0 };
		e.stopImmediatePropagation();
	}, true );
	dom.addEventListener( 'pointermove', ( e ) => {
		if ( ! bwTouch || e.pointerId !== bwTouch.id ) return;
		bwTouch.f = Math.max( - 1, Math.min( 1, - ( e.clientY - bwTouch.y ) / 60 ) );
		bwTouch.r = Math.max( - 1, Math.min( 1, ( e.clientX - bwTouch.x ) / 60 ) );
		e.stopImmediatePropagation();
		invalidate( 2 );
	}, true );
	const up = ( e ) => { if ( bwTouch && e.pointerId === bwTouch.id ) bwTouch = null; };
	addEventListener( 'pointerup', up, true );
	addEventListener( 'pointercancel', up, true );
}

/* `#walk-C1` walks in at entrance 1, `#flat-37/walk` walks into flat 37. */
function bwHash() {
	const h = decodeURIComponent( location.hash || '' );
	let m = /^#walk-(C\d|podium)$/i.exec( h );
	if ( m ) return bwWalk( { portal: m[ 1 ].toUpperCase() === 'PODIUM' ? 'podium' : m[ 1 ].toUpperCase() }, { from: 'street' } );
	m = /^#flat-(.+)\/walk$/.exec( h );
	if ( m ) return bwWalkFlat( m[ 1 ] );
	return null;
}
/* A flat by its number: its level opens, and the visitor walks in from its
 * own front door. */
function bwWalkFlat( n ) {
	return LVL.planMeta().then( async ( pm ) => {
		lvPM = pm;
		const u = LVL.flatByN( n );
		if ( ! u ) return false;
		/* The level first - the floor view, the flat lit on it - and then the
		 * dive in at its door: from the street that is the way the building
		 * opens, not a camera flying through its roof. */
		if ( ! ( sceneNo === 2 && scene2View === 'plan' && lvOpen === u.level ) ) {
			if ( bwOn ) bwExit( 'none' );
			lvOpenLevel( u.level, u.n );
			const t0 = performance.now();
			while ( performance.now() - t0 < 60000 && ! ( sceneNo === 2 && scene2View === 'plan' && lvOpen === u.level
				&& ! tweens.length && ! lvWaiting ) ) await nextFrame();
			if ( ! ( sceneNo === 2 && lvOpen === u.level ) ) return false;
		}
		return bwWalk( { flat: u.n }, { from: 'level' } );
	} );
}

/* The furniture of one level: web/interior/furn/<LEVEL>.glb + index.json,
 * fetched once the level itself is in, compiled through the same gate as
 * the interiors, hidden (every piece at scale 0) until a flat asks for it.
 * Never awaited by the floor view: a level opens without it, and the hover
 * furnishes the flat under the pointer from the moment it is here. */
let lvFurnIdx = null;
function lvFurnIndex() {
	if ( ! lvFurnIdx ) lvFurnIdx = fetch( './interior/furn/index.json', LVL.jsonInit() )
		.then( r => r.ok ? r.json() : null ).catch( () => null )
		.then( ( j ) => { if ( ! j ) lvFurnIdx = null; return j; } );
	return lvFurnIdx;
}
/* LV_ORDER (step 2-storey): the furniture's bytes are asked for at the
 * moment of intent (`lvFurnPrefetch` from the click, the dwell and the
 * prewarm), not after the level has been fetched, welded and compiled -
 * the index first (memoised, so from the second storey on the GLB starts
 * at once), then the GLB, held here until `lvFurn` takes it. Nothing is
 * parsed or built early; only the fetch moves. The floor maps go after the
 * level's own bytes (`lvPart`). `?lvorder=old` restores the old order. */
const LV_ORDER = __q.get( 'lvorder' ) !== 'old';
const lvFurnPre = new Map();
function lvFurnPrefetch( name ) {
	if ( ! LV_ORDER || ! name || name === 'cores' || lvFurnPre.has( name ) ) return;
	const P = lvParts.get( name );
	if ( P && P.furnReady ) return;
	const pr = lvFurnIndex().then( ( ix ) => ( ix && ix.levels && ix.levels[ name ] ) ? LVL.fetchPart( 'furn/' + name ) : null );
	pr.catch( () => {} );
	lvFurnPre.set( name, pr );
	// a prefetch nobody took (the click went elsewhere) lets go of its bytes
	setTimeout( () => { if ( lvFurnPre.get( name ) === pr ) lvFurnPre.delete( name ); }, 60000 );
}
function lvFurn( P ) {
	if ( ! P || P.name === 'cores' ) return Promise.resolve( null );
	if ( P.furnReady ) return P.furnReady;
	P.furnState = 'loading';
	P.furnReady = ( async () => {
		const T = [ performance.now() ], tick = () => T.push( performance.now() );
		if ( LV_ORDER ) lvFurnPrefetch( P.name );
		const pre = LV_ORDER ? lvFurnPre.get( P.name ) : null;
		if ( pre ) lvFurnPre.delete( P.name );
		const ix = await lvFurnIndex();
		const lv = ix && ix.levels && ix.levels[ P.name ];
		if ( ! lv ) { P.furnState = 'none'; return null; }
		// never into a flight: a compile holds the frame loop off
		for ( let i = 0; i < 400 && tweens.length; i ++ ) await nextFrame();
		tick();
		const buf = ( pre && await pre.catch( () => null ) ) || await LVL.fetchPart( 'furn/' + P.name );
		tick();
		if ( P.state === 'gone' ) { P.furnState = 'none'; return null; }
		const gltf = await new Promise( ( res, rej ) => glbLoader.parse( buf, './', res, rej ) );
		tick();
		const holder = new THREE.Group();
		holder.matrixAutoUpdate = false;
		holder.matrix.copy( frameP.matrix );
		holder.add( gltf.scene );
		const F = LVL.buildFurniture( holder, lv, ( n ) => ( sceneMaterials && sceneMaterials[ n ] ) || null,
			( miss ) => console.warn( 'unmapped materials in interior/furn/' + P.name + ':', miss ) );
		if ( P.state === 'gone' ) { P.furnState = 'none'; return null; }
		tick();
		P.group.add( F.group );
		await lvFurnCompile( P, F );
		tick();
		P.furn = F;
		P.furnAll = 0;
		P.furnSolids = furnitureSolids( lv, ( p ) => F.heights.get( p.node ) );
		if ( bwW ) {
			const r = bwW.solids( P.name, P.furnSolids );
			if ( r && r.dropped.length ) console.info( 'furniture ' + P.name + ': ' + r.dropped.length + ' pieces in a doorway are not solid' );
		}
		P.furnState = 'in';
		console.info( 'furniture ' + P.name + ': ' + F.pieces + ' pieces, ' + Math.round( F.tris ) + ' triangles placed, '
			+ F.instanced.children.length + ' piece meshes, ' + F.reps.length + ' kinds (' + F.welded().children.length + ' welded, for a walk); ms wait/fetch/parse/build/compile '
			+ T.slice( 1 ).map( ( t, i ) => Math.round( t - T[ i ] ) ).join( '/' ) );
		lvFurnSync( P );
		return F;
	} )();
	P.furnReady.catch( ( e ) => { console.warn( 'furniture ' + P.name + ' did not load:', e ); P.furnState = 'none'; } );
	return P.furnReady;
}
const lvFurnWarmed = new Set();
const lvFurnWalked = new Set();
/* One piece per shader, not one per (geometry, material). Every input of
 * three's state and pipeline keys that differs between pieces is here: the
 * material, the attribute layout (name, size, normalised, interleave, array
 * type) and a mirrored matrix (front face). receiveShadow, the clipping
 * context and the absence of morphs are the same for every piece. 788 kinds
 * on L06 are 32 shaders; warming them all was ~69 loop-held lots, ~3 s.
 * `?furnwarm=all` warms every kind, as before. */
const FURN_WARM_ALL = __q.get( 'furnwarm' ) === 'all';
/* Pieces compiled per loop-held lot. With one piece per shader every piece
 * in a lot is a new shader build (~35 ms of WGSL each), so a dozen was a
 * 450 ms frozen frame; with every kind, most of a dozen were repeats. */
const FURN_LOT = + ( __q.get( 'furnlot' ) || ( FURN_WARM_ALL ? 12 : 4 ) );
function furnWarmSet( reps ) {
	if ( FURN_WARM_ALL ) return reps;
	const seen = new Map();
	for ( const o of reps ) {
		const g = o.geometry;
		let k = o.material.uuid + '|' + ( o.matrix.determinant() < 0 ? 'cw' : 'ccw' );
		for ( const n of Object.keys( g.attributes ).sort() ) {
			const a = g.attributes[ n ];
			k += '|' + n + ',' + a.itemSize + ',' + ( a.normalized ? 'n' : '' ) + ',' + ( a.data ? a.data.stride + ':' + a.offset : '' )
				+ ',' + ( a.array && a.array.constructor.name );
		}
		if ( Object.keys( g.morphAttributes ).length ) k += '|' + g.uuid;
		if ( ! seen.has( k ) ) seen.set( k, o );
	}
	return [ ...seen.values() ];
}
/* The walk's welded furniture, built in slices a frame apart (levels.js
 * `weldedAsync`) - the one-task weld was the bulk of every storey entry's
 * worst frame. `?weldslice=0` welds in one go, as before. */
const WELD_SLICE = __q.get( 'weldslice' ) !== '0';
function lvFurnWeld( F ) {
	return WELD_SLICE ? F.weldedAsync( nextFrame ) : Promise.resolve( F.welded() );
}
function lvFurnCompile( P, F ) {
	/* On a walk only the welded variant is wanted, and it is built the walk's
	 * way (`lvWarmWalk`); the floor view's instanced one is built behind the
	 * gate the first time a floor view needs it. */
	if ( bwOn && BW_ASYNC && PIPES ) return lvFurnWeld( F ).then( ( W ) => {
		const mats = new Set( W.children.filter( o => o.isMesh ).map( o => o.material )
			.concat( [ ...W.userData.keepInst ] ) );
		let gWas = false, capWas = false;
		return lvWarmWalk( P, () => {
			gWas = P.group.visible;
			if ( P.cap ) { capWas = P.cap.visible; P.cap.visible = false; }
			P.group.visible = true;
			F.walk( true );
		}, () => {
			// the level as the walk had it; `lvFurnSync` puts the pieces right once it is 'in'
			if ( ! ( bwOn && bwShown.has( P.name ) ) ) { F.walk( false ); F.all( 0 ); P.group.visible = gWas; }
			if ( P.cap ) P.cap.visible = capWas;
		}, mats, lvFurnWalked );
	} );
	const job = lvWarm.then( async () => {
		/* Both ways it is drawn - instanced in the floor view, welded on a
		 * walk - are pipelines of their own; both are built here, behind the
		 * gate, so neither is a first draw in front of a visitor. */
		const W = await lvFurnWeld( F );
		const mats = new Set( F.instanced.children.map( o => o.material ) );
		const key = ( m ) => m.uuid;
		if ( ! [ ...mats ].every( m => lvFurnWarmed.has( key( m ) ) ) ) {
			/* A dozen meshes at a time with a frame let through between the
			 * batches: all of it at once is 4-6 s with the frame loop held,
			 * and this runs behind a street the visitor is looking at. */
			W.visible = true;
			const kids = [ ...furnWarmSet( F.reps ), ...W.children ], was = kids.map( o => o.visible );
			for ( const o of kids ) o.visible = false;
			const instBack = F.instHold ? F.instHold() : () => {};   // FURN_GRAPH
			try {
				for ( let i = 0; i < kids.length; i += FURN_LOT ) {
					const lot = kids.slice( i, i + FURN_LOT );
					for ( const o of lot ) o.visible = true;
					await compileInto( prePass, [ lvRoot ], P.group );
					await compileInto( scenePass, [ lvRoot ], P.group );
					for ( const o of lot ) o.visible = false;
					if ( i + FURN_LOT < kids.length ) await nextFrame();
				}
			}
			finally {
				W.visible = false;
				kids.forEach( ( o, i ) => { o.visible = was[ i ]; } );
				instBack();
			}
			for ( const m of mats ) lvFurnWarmed.add( key( m ) );
		}
	} );
	lvWarm = job.catch( () => {} );
	return job;
}
/* A level's furniture as the view wants it: all of it while walking, else
 * the floor view's dials - the hovered and the open flat, and no other. */
function lvFurnSync( P ) {
	const F = P && P.furn;
	if ( ! F ) return;
	if ( bwOn && bwShown.has( P.name ) ) { if ( F.walk( true ) ) shadowDirty(); P.furnAll = 1; invalidate( 2 ); return; }
	F.walk( false );
	F.all( 0 );
	P.furnAll = 0;
	const L = lvLevel( P.name );
	if ( L && lvOpen === P.name && sceneNo === 2 )
		for ( let k = 1; k <= Math.min( L.units.length, LVL.MAX_UNITS - 1 ); k ++ )
			if ( lvRev[ k ] > 0 ) F.reveal( L.units[ k - 1 ].token, lvRev[ k ] );
	shadowDirty();
	invalidate( 2 );
}

function initEmbed() {

	controls.enableZoom = false;          // the wheel belongs to the page
	controls.enablePan = false;
	controls.rotateSpeed = 0.45;
	controls.enableDamping = true;
	controls.dampingFactor = 0.07;

	const dom = renderer.domElement;
	/* The rail has to let go the moment the visitor takes the camera, and it
	 * has to do it BEFORE the controls act on the same event, so the fly
	 * controls read the orientation the rail has just left behind. Without
	 * this the rail puts the camera back on its own path every frame and
	 * walking with W A S D goes nowhere. */
	dom.addEventListener( 'pointerdown', railWake, true );
	dom.addEventListener( 'wheel', railWake, { capture: true, passive: true } );
	addEventListener( 'keydown', ( e ) => {
		if ( /^(Arrow|Key[WASDQEC]|Space|Shift)/.test( e.code ) ) railWake();
	}, true );
	embedCursor( false );
	dom.addEventListener( 'pointerdown', () => embedCursor( true ) );
	addEventListener( 'pointerup', () => embedCursor( false ) );

	/* Where the pointer is. The test itself is `floorTest`, which the frame
	 * loop also runs whenever the view has moved: the hero camera is never
	 * parked, so a pointer sitting still is over a different storey a second
	 * later, and testing on pointermove alone leaves the wrong floor lit. */
	dom.addEventListener( 'pointermove', ( e ) => {
		floorPointer = [ e.clientX, e.clientY ];
		floorDirty = true;                 // tested once on the next frame
		/* A pointer crossing the facade is a visitor DOING something, not
		 * one standing and looking, so the still frame's supersampling is
		 * put off until they stop: a storey that answers the pointer has to
		 * answer it at once, and it cannot while every frame is 2.25 times
		 * the work. The dwell starts again from here. */
		stillFrames = 0;
		invalidate( 2 );
	} );
	dom.addEventListener( 'pointerleave', () => {
		floorPointer = null; floorDirty = true; setHotFloor( 0 );
	} );

	/* The floor view slides under the pointer. These are bound before the
	 * click that opens a storey and do nothing outside the plan view; the
	 * fly controls are told to keep their hands off the drag there
	 * (`drag:` in the options above), so only one of the two ever has it. */
	dom.addEventListener( 'pointerdown', planPointerDown );
	dom.addEventListener( 'pointermove', planPointerMove );
	addEventListener( 'pointerup', planPointerUp );
	addEventListener( 'pointercancel', planPointerUp );

	/* A click on the building - not on the sky, and not the end of a drag -
	 * is the way into the flat, and WHERE on the building says which storey
	 * opens. The storey is the hover's own answer, so what opens is what has
	 * been lit under the pointer all along; a click that lands on the block
	 * but on no storey - the podium, the shopfront, the roof - opens the top
	 * floor, which is what the whole building did before. The raycast runs
	 * once per click, against the groups that make up the street, so a miss
	 * costs nothing. */
	const ray = new THREE.Raycaster();
	const ndc = new THREE.Vector2();
	let downAt = null;
	dom.addEventListener( 'pointerdown', ( e ) => { downAt = [ e.clientX, e.clientY ]; } );
	dom.addEventListener( 'pointerup', ( e ) => {
		if ( ! downAt ) return;
		const slid = Math.hypot( e.clientX - downAt[ 0 ], e.clientY - downAt[ 1 ] );
		downAt = null;
		/* In the floor view a click is the THIRD step: it opens the flat it
		 * lands on, and the camera comes down onto that one unit. The same
		 * click off the plan - the roof, the air beside the block - closes
		 * it again and gives the storey back, which is the way out that
		 * needs no button. The slide test above is what keeps a drag of the
		 * row from counting as a click on whatever it stopped over. */
		/* ...but not from INSIDE one. There the same click is a visitor
		 * letting go of a drag they used to look round the room, and the
		 * ray would land on the plan of whatever flat happens to lie
		 * under the wall they are facing. */
		if ( FLAT_GONE && slid <= 5 && ! tweens.length && planDragOwns() && roomFocus < 0 ) {
			const k = lvUnitUnder( [ e.clientX, e.clientY ] );
			if ( k !== lvFocusK ) lvFocus( lvUnit( k ) );
			return;
		}
		if ( slid <= 5 && ! tweens.length && planDragOwns() && roomFocus < 0 ) {
			const u = planUnitUnder( [ e.clientX, e.clientY ] );
			if ( u !== planFocus ) planFocusSet( u );
			return;
		}
		if ( slid > 5 || sceneNo !== 1 || tweens.length ) return;
		/* The real building: the level that is lit, else whatever band the
		 * click itself lands on - and through the gate, never onto a level
		 * that is not here yet. A click on the building that lands on no
		 * storey (the podium, the roof) opens the show flat, as it opened
		 * the tour before. */
		if ( FLAT_GONE ) {
			/* A street door: the camera walks up to it and the visitor is
			 * on foot from there. */
			const door = bwHot || bwDoorUnder( [ e.clientX, e.clientY ] );
			if ( door ) { bwWalk( { portal: door }, { from: 'street' } ); return; }
			const id = lvHotLevel || lvBandUnder( [ e.clientX, e.clientY ] );
			if ( id ) { lvOpenLevel( id ); return; }
			const r = dom.getBoundingClientRect();
			ndc.set( ( e.clientX - r.left ) / r.width * 2 - 1, - ( ( e.clientY - r.top ) / r.height ) * 2 + 1 );
			ray.setFromCamera( ndc, camera );
			if ( ray.intersectObjects( [ groups.main, groups.tower ].filter( Boolean ), true )
				.some( h => h.object.isMesh && h.object.visible ) ) setScene( 2 );
			return;
		}
		/* The storey that was LIT, not a fresh cast. `floorHot` is what the
		 * amber band and the hover card are both showing; casting again here
		 * asks the question a second time, against a camera that has moved
		 * since - the hero rides a rail and is never parked - so a click on
		 * the floor you can see highlighted opened its neighbour. Only fall
		 * back to a cast if nothing is lit at all. */
		const storey = floorHot || floorUnder( [ e.clientX, e.clientY ] );
		/* ...and not into an EMPTY floor view. The hover is armed on the
		 * flat being here, but a click does not have to come through a
		 * hover - the fallback cast below opens the top floor from
		 * anywhere on the block - so this is the other way in and it
		 * needs the same gate. On a slow link the flight takes two
		 * seconds of the wait with it. */
		if ( storey ) return withFlat( () => setScene( 2, true, storey, 'plan' ) );
		const r = dom.getBoundingClientRect();
		ndc.set( ( e.clientX - r.left ) / r.width * 2 - 1,
			- ( ( e.clientY - r.top ) / r.height ) * 2 + 1 );
		ray.setFromCamera( ndc, camera );
		const groupsNow = [ groups.main, groups.tower ].filter( Boolean );
		const hit = ray.intersectObjects( groupsNow, true )
			.some( h => h.object.isMesh && h.object.visible );
		if ( hit ) withFlat( () => setScene( 2 ) );
	} );

	buildFloorMap();
	lvBuildBands();
	bwBuildDoors();
	// ...and not here: the page opens on the street, where the shot is the
	// solved one and nobody is allowed to drag it off. `flyApply` decides.
	flyApply();

	/* What the page outside is allowed to do to the scene. */
	window.LP = {
		get scene() { return sceneNo; },
		// the storey scene 2 is open on, for the page's flat card
		get floor() { return sceneFloor || topFloor(); },
		get topFloor() { return topFloor(); },
		get busy() { return tweens.length > 0; },
		// `view` picks between scene 2's two: the flat from outside, or the
		// storey from above that a visitor walks a flat out of
		setScene: ( n, floor, view ) =>
			setScene( n, true, floor || topFloor(), view || 'hero' ),
		/* How many CSS pixels of the left of the frame the page is sitting
		 * on. Set it before the scene changes and the flight is already
		 * aimed at the clear part; set it after a resize and the shot
		 * re-frames where it stands. */
		setInset( px ) {
			const v = Math.max( 0, + px || 0 );
			if ( v === uiInset ) return;
			uiInset = v;
			uiRefit();
		},
		/* Where down the frame the cards begin, in the same pixels. The
		 * storey's top edge is laid on that line; see `uiTop`. */
		setTop( px ) {
			const v = Math.max( 0, + px || 0 );
			if ( v === uiTop ) return;
			uiTop = v;
			uiRefit();
		},
		/* ...and how much of its foot, for the narrow layout's docked
		 * card. Only the open flat is framed against it. */
		setFoot( px ) {
			const v = Math.max( 0, + px || 0 );
			if ( v === uiFoot ) return;
			uiFoot = v;
			uiRefit();
		},
		/* The floor view, walked along the row. `planSteps` is how many
		 * stops there are - one per flat, plus the end of the row - and
		 * `planStep` which one it is on, so the page can grey out an arrow
		 * at either end. */
		get planSteps() {
			return ( sceneNo === 2 && scene2View === 'plan' ) ? planStops().length : 0;
		},
		get planStep() { return planStep; },
		planStepBy: ( d ) => planStepBy( d | 0 ),
		planStepTo: ( i ) => planStepTo( i ),
		/* The open flat: which of the eight units the floor view has come
		 * down onto, or -1 for the whole storey. The page reads it to know
		 * which card to show and writes it to close the flat again. */
		get planFocus() {
			return ( sceneNo === 2 && scene2View === 'plan' ) ? planFocus : - 1;
		},
		planFocusTo: ( i ) => planFocusSet( i == null ? - 1 : i | 0 ),
		/* ...and which room of the open flat the camera is standing in,
		 * or -1 for the flat itself. The page reads it to know whether to
		 * show the way out, and writes it when a dot is clicked. */
		get room() { return roomOwns() ? roomFocus : - 1; },
		get rooms() { return ROOMS.map( ( r, i ) => ( { i, key: r.key, name: r.name } ) ); },
		roomTo: ( i ) => roomSet( i == null ? - 1 : i | 0 ),
		roomBy: ( d ) => {
			if ( roomFocus < 0 ) return;
			roomSet( ( roomFocus + ( d | 0 ) + ROOMS.length * 2 ) % ROOMS.length );
		},
		setMode: ( m ) => setMode( m ),
		reset: () => setMode( 'hero' ),
		pose: () => flyPose(),
		// the hero is off screen: stop listening for WASD
		set active( v ) { flyAllowed = !! v; },
		invalidate,
		// what the camera is being driven by, for diagnosis
		get drive() { return { fly: fly.enabled, orbit: controls.enabled, mode,
			railIdle: performance.now() - railTouchAt, allowed: flyAllowed,
			railT: + railT.toFixed( 4 ), railBusy, tweens: tweens.length,
			hold: Math.round( railHoldUntil - performance.now() ),
			offRail: + camera.position.distanceToSquared( railPose( railT ).p ).toFixed( 4 ) }; },
	};
	// ...and the real building's levels, over the old members of the same names
	if ( FLAT_GONE ) lvInstallApi( window.LP );

}

/* ---------------------------------------------------------------- post */
function buildPipeline() {

	pipeline = new THREE.RenderPipeline( renderer );

	prePass = pass( scene, camera );
	prePass.name = 'prepass';
	prePass.transparent = false;
	/* The pre-pass writes normals for the occlusion and velocity for the
	 * temporal AA. `normalView` is the SHADED normal, so asking for it makes
	 * every material's normal-map chain - the triplanar noise and the
	 * weathering in materials.js - run a second time, in a pass whose output
	 * is a low frequency occlusion term that cannot show it. `?prenorm=geo`
	 * asks for the geometry's own normal instead. */
	const PRE_GEO = new URLSearchParams( location.search ).get( 'prenorm' ) === 'geo';
	prePass.setMRT( mrt( { output: packNormalToRGB( PRE_GEO ? normalViewGeometry : normalView ),
		velocity } ) );
	/* The pre-pass writes a normal and a velocity and NOTHING else - and
	 * three.js builds it a full PBR shader anyway. Measured on this page:
	 * every material gets TWO lit programs of about 45 KB, one for each pass,
	 * and of the 3.8 MB of WGSL the boot generates 1.7 MB is the pre-pass
	 * working out a BRDF, sixteen shadow taps, a PMREM lookup and the fog
	 * that neither of its two outputs can show. Generating WGSL is what the
	 * boot and the hover's wait ARE - 914 ms of the boot's warm frame, of
	 * which 565 ms vanishes if the lighting chain is not built (?nolight=1
	 * prices it) - so this is the biggest single thing on the page's clock.
	 *
	 * `renderer.lighting.enabled` is the flag three.js reads when it decides
	 * whether to build a material's lighting at all
	 * (`NodeMaterial.setupLighting`), and the two passes keep separate node
	 * builder states, so turning it off around the pre-pass' own render and
	 * back on afterwards gives the pre-pass lightless shaders and leaves the
	 * beauty pass exactly as it was. Nothing the pre-pass outputs depends on
	 * lighting, so the picture does not move: measured at 0.0/255.
	 * ?prelight=1 builds it the old way, for the A/B. */
	/* It has to stay off for EVERY frame, not just the ones that build the
	 * shaders. Scoping it to the two warms was tried - the states are cached
	 * at first build, so in principle that is all it needs - and it costs
	 * more than it saves: three.js treats the flag as part of what a state
	 * was built for, so flipping it back makes it build every pre-pass
	 * material a second time. The boot kept its 280 ms and the show flat's
	 * warm went from 1.1 s to 2.9. ?prelight=1 builds it the old way. */
	if ( __q.get( 'prelight' ) !== '1' ) {
		const inner = prePass.updateBefore.bind( prePass );
		prePass.updateBefore = ( frame ) => {
			const was = renderer.lighting.enabled;
			renderer.lighting.enabled = false;
			try { return inner( frame ); } finally { renderer.lighting.enabled = was; }
		};
	}
	const prePassNormal = sample( ( uv ) => unpackRGBToNormal( prePass.getTextureNode().sample( uv ) ) );
	const prePassDepth = prePass.getTextureNode( 'depth' );
	const prePassVel = prePass.getTextureNode( 'velocity' );
	prePass.getTexture( 'output' ).type = THREE.UnsignedByteType;

	scenePass = pass( scene, camera );
	scenePass.setMRT( mrt( { output, velocity } ) );

	aoPass = ao( prePassDepth, prePassNormal, camera );
	aoPass.distanceExponent.value = 1.4;
	aoPass.distanceFallOff.value = 0.6;
	aoPass.radius.value = 0.85;
	aoPass.scale.value = 1.0;
	aoPass.thickness.value = 1.2;
	scenePass.contextNode = builtinAOContext(
		mix( float( 1.0 ), aoPass.getTextureNode().sample( screenUV ).r, aoStrength ) );

	const beauty = scenePass.getTextureNode();
	const vel = scenePass.getTextureNode( 'velocity' );

	// temporal AA resolves the GTAO noise and the leaf edges
	const stabilised = traa( beauty, prePassDepth, prePassVel, camera );
	traaNode = stabilised;                  // for the warm-up: see `warmUp`
	const glow = bloom( stabilised, 0.20, 0.46, 0.90 );
	// A touch over a pixel of lateral fringing at the frame edge - any more and
	// it stops reading as a lens and starts reading as an effect, which is
	// what 0.55 did: high-contrast edges low in the frame, the road markings
	// above all, came back visibly rainbowed.
	const img = chromaticAberration(
		stabilised.add( glow ), gradeAmount.mul( 0.28 ), vec2( 0.5, 0.5 ), 0.10 );

	// --- grade: vignette + fine grain, both on a single switch
	const vign = screenUV.sub( vec2( 0.5, 0.5 ) ).mul( vec2( 1.08, 0.94 ) ).length()
		.remapClamp( 0.30, 0.92, 1.0, 0.72 );
	const grain = fract( sin(
		dot( screenUV.mul( vec2( 1731.0, 977.0 ) ), vec2( 12.9898, 78.233 ) )
	).mul( 43758.5453 ) );

	const graded = img.rgb
		.mul( mix( float( 1.0 ), vign, gradeAmount.mul( vignAmount ) ) )
		.add( grain.sub( 0.5 ).mul( 0.013 ).mul( gradeAmount ) );

	pipeline.outputNode = vec4( graded, 1.0 );

	// probe handles for tools/perf-probe.cjs (no effect on the render)
	window.__parts = { pipeline, prePass, scenePass, aoPass };
	/* The four groups the scene is built out of, for the cost rigs: what is
	 * standing in the frame is the first question any of them asks, and the
	 * only way to answer it from outside is to be able to take a group away
	 * and measure the frame without it. */
	window.__groups = () => groups;
	window.__density = () => ( { basePR: + basePR.toFixed( 3 ), pr: + renderer.getPixelRatio().toFixed( 3 ),
		step: prStep, adaptive: ADAPT, still: stillNow(), ss: + stillScale().toFixed( 3 ),
		msPerMpx: + msPerMpx.toFixed( 2 ), msPerMpxFlat: + msPerMpxFlat.toFixed( 2 ),
		inFlat: inFlat(), cityHidden, cap: prCap,
		mpx: + ( innerWidth * innerHeight * renderer.getPixelRatio() ** 2 / 1e6 ).toFixed( 2 ) } );
	/* where the floor view has been slid to, for the drag rigs */
	/* What the open flat's fit actually did: the stand-off it landed on and
	 * where the unit's own box ends up on the screen, in CSS pixels,
	 * against the band it was fitted to. The fit is five passes of
	 * measuring and there is no reading it off the camera afterwards - a
	 * pose that has diverged and a pose that is right look the same from
	 * outside. */
	/* `__focus( u )` opens a flat from the console or a shot script, the
	 * way `__room` walks into one: the page itself does it by clicking the
	 * plan, which a headless browser cannot aim. */
	window.__focus = ( u ) => {
		if ( u !== undefined ) planFocusSet( u == null ? - 1 : u | 0, false );
		if ( planFocus < 0 ) return { focus: - 1 };
		const box = planUnitBox( planFocus );
		if ( ! box ) return { focus: planFocus, box: null };
		const F = planFrame();
		const b = meta && meta.block && meta.block.floors;
		const head = ( ( b && b.h ) || 3 ) - 0.2;
		const fw = F.fw, fh = frameEl.clientHeight || 1;
		const q = new THREE.Vector3();
		let x0 = Infinity, x1 = - Infinity, y0 = Infinity, y1 = - Infinity;
		for ( const x of [ box.x0, box.x1 ] )
			for ( const y of [ box.y0, box.y1 ] )
				for ( const z of [ 0, head ] ) {
					q.copy( F.o ).addScaledVector( F.ex, x )
						.addScaledVector( F.ey, y ).setY( F.o.y + z ).project( camera );
					const px = ( q.x * 0.5 + 0.5 ) * fw, py = ( - q.y * 0.5 + 0.5 ) * fh;
					x0 = Math.min( x0, px ); x1 = Math.max( x1, px );
					y0 = Math.min( y0, py ); y1 = Math.max( y1, py );
				}
		const t = new THREE.Vector3( ...( camera.position.toArray() ) );
		return { focus: planFocus, fov: + camera.fov.toFixed( 1 ),
			d: + camera.position.distanceTo(
				F.o.clone().addScaledVector( F.ex, ( box.x0 + box.x1 ) * 0.5 )
					.addScaledVector( F.ey, ( box.y0 + box.y1 ) * 0.5 ) ).toFixed( 2 ),
			box: [ x0, y0, x1, y1 ].map( v => Math.round( v ) ),
			size: [ Math.round( x1 - x0 ), Math.round( y1 - y0 ) ],
			frame: [ fw, fh ], inset: Math.round( uiInset ), top: Math.round( uiTop ),
			foot: Math.round( uiFoot ) };
	};
	/* Walk into a room from the console or a shot script - the page itself
	 * does it by clicking a dot, which a headless browser cannot aim. */
	window.__room = ( i ) => {
		if ( i !== undefined ) roomSet( i == null ? - 1 : i | 0, false );
		return { room: roomFocus, focus: planFocus,
			key: roomFocus >= 0 ? ROOMS[ roomFocus ].key : null,
			shell: !! roomShell, shellOn: roomShellOn, shellUnit: roomShellUnit,
			fov: + camera.fov.toFixed( 1 ), y: + camera.position.y.toFixed( 2 ),
			ceiling: + roomCeilingY().toFixed( 2 ) };
	};
	/* Where the body is standing, how much floor it has round it, and how
	 * far each of the four doors has swung. There is nothing to read off
	 * the camera here either: a walk that is sliding along a wall it should
	 * have stopped at and one that is walking down the middle of the hall
	 * look the same from outside, and `free` is the number that tells them
	 * apart - it must never fall below `WK.R` while a body is in the open. */
	/* `__walk( [ x, y ], [ ax, ay ] )` stands the body at a point in the
	 * flat's own plan and faces it at another, which is how a shot script
	 * aims at a door - the page itself does it by dragging, which a
	 * headless browser can only do in pixels and cannot aim. */
	window.__walk = ( at, aim ) => {
		if ( at && walkOn ) {
			walk.x = at[ 0 ]; walk.y = at[ 1 ];
			walk.vx = walk.vy = 0;
			if ( aim ) {
				const { ex, ey } = flatFrame();
				const d = ex.clone().multiplyScalar( aim[ 0 ] - at[ 0 ] )
					.addScaledVector( ey, aim[ 1 ] - at[ 1 ] ).normalize();
				camera.quaternion.setFromRotationMatrix(
					new THREE.Matrix4().lookAt( new THREE.Vector3(),
						d.negate(), new THREE.Vector3( 0, 1, 0 ) ) );
				if ( fly ) fly.sync();
			}
			walkPlace();
			invalidate();
		}
		return {
			on: walkOn, eye: walk.eye,
			at: [ + walk.x.toFixed( 2 ), + walk.y.toFixed( 2 ) ],
			v: + Math.hypot( walk.vx, walk.vy ).toFixed( 2 ),
			// `free` is the two together; `plan` is the grid alone, so a
			// body hemmed in by a door reads differently from one hemmed
			// in by a wall
			free: + walkFree( walk.x, walk.y ).toFixed( 3 ), need: WK.R,
			plan: + walkDist( walk.x, walk.y ).toFixed( 3 ),
			bob: [ + walk.bobY.toFixed( 4 ), + walk.sway.toFixed( 4 ) ],
			grid: walkGrid
				? { unit: walkGridUnit, cells: [ walkGrid.nx, walkGrid.ny ] } : null,
			// what the build shipped as swinging, per material: four doors
			// times eight units, or the rig is hanging half a door
			swing: [ ...doorSwing ].map( ( [ n, S ] ) => n + ':' + S.by.size ),
			doors: doorRig ? doorRig.doors.map( d => ( { key: d.D.key,
				t: + d.t.toFixed( 2 ), shut: ! d.latched,
				at: d.world.map( v => + v.toFixed( 2 ) ) } ) ) : null,
		};
	};
	window.__plan = () => ( { pan: planPanM, vel: planVel, limit: planLimit(),
		step: planStep, stops: planStops().map( x => + x.toFixed( 2 ) ),
		dragging: !! planDrag } );
	/* the floor view's drawing: which flat is lit and how far each has come */
	/* `__plan2d( unit )` lights a flat from the console; a second argument
	 * PINS how far that flat is furnished and stops the dial moving, which
	 * is the only way to photograph a stagger whose whole life is a second
	 * long. Call it again with no arguments to let go. */
	window.__plan2d = ( u, t ) => {
		if ( u !== undefined ) { planHot = u | 0; planHold = 0; invalidate( 8 ); }
		planPin = ( t === undefined || t === null ) ? - 1 : + t;
		/* The clock is set alongside the dial - not its exact inverse, but
		 * enough that letting the pin go carries on from roughly where the
		 * shot was rather than from wherever the clock was left. */
		if ( planPin >= 0 ) {
			planRev[ planHot ] = planPin;
			planRevT[ planHot ] = planPin;
			planWrite();
		}
		return { on: planDrawOwns(), amt: + planAmt.toFixed( 3 ), hot: planHot, pin: planPin,
			hold: + planHold.toFixed( 2 ), view: scene2View, scene: sceneNo,
			steps: planSteps, rev: planRev.map( v => + v.toFixed( 3 ) ) };
	};
	/* which storey is hot and how far each slot is open, for tools/hovercost.cjs */
	window.__floor = () => ( { hot: floorHot, armed: floorArmed,
		slots: floorSlots.map( s => ( { n: s.n, open: + s.open.toFixed( 3 ),
			flat: !! ( s.flat && s.flat.visible ) } ) ) } );
	/* Open scene 2 on a storey from the console or a shot script - the page
	 * itself does it with a click, which a headless browser cannot aim. */
	window.__storey = ( n, view ) => { setScene( n ? 2 : 1, true, n || topFloor(), view || 'hero' );
		return { scene: sceneNo, floor: sceneFloor, view: scene2View }; };
	window.__dbg = ( k ) => {
		const map = { scene: scenePass, beauty, traa: stabilised,
			bloom: glow, img, final: vec4( graded, 1.0 ),
			ao: vec4( vec3( aoPass.getTextureNode().sample( screenUV ).r ), 1 ) };
		pipeline.outputNode = map[ k ];
		pipeline.needsUpdate = true;
		return k;
	};

}

/* ---------------------------------------------------------------- ui */
function wireUI() {
	const on = ( id, fn ) => $( id ).addEventListener( 'change', ( e ) => fn( e.target.checked ) );
	on( 't_ao', v => { aoStrength.value = v ? 1.0 : 0.0; invalidate(); } );
	on( 't_grade', v => { gradeAmount.value = v ? 1.0 : 0.0; invalidate(); } );
	on( 't_cmp', v => setCompare( v && sceneNo === 1 ) );
	[ 'hero', 'orbit', 'fly' ].forEach( k =>
		$( 'm_' + k ).addEventListener( 'click', () => setMode( k ) ) );
	$( 's_1' ).addEventListener( 'click', () => setScene( 1 ) );
	// the real building's scene 2 has its own gate (`lvWith`)
	$( 's_2' ).addEventListener( 'click', () => FLAT_GONE ? setScene( 2 ) : withFlat( () => setScene( 2 ) ) );
	$( 'm_top' ).addEventListener( 'click', () => setMode( 'top' ) );
	$( 'm_row' ).addEventListener( 'click', () => setMode( 'row' ) );
	on( 't_plan', v => setPlan( v ) );
	on( 't_mirror', v => { planMirror = v; planFlip.value = v ? 1.0 : 0.0; invalidate(); } );
	// hides everything we built, so the plan can be read on its own
	on( 't_hide', v => { if ( groups.flat ) groups.flat.visible = ! v && sceneNo === 2;
		shadowDirty(); invalidate(); } );
	// batching is decided once at load, so the switch reloads with the flag
	const dev = $( 't_dev' );
	dev.checked = DEV;
	dev.addEventListener( 'change', ( e ) => {
		const u = new URL( location.href );
		if ( e.target.checked ) u.searchParams.set( 'dev', '1' );
		else u.searchParams.delete( 'dev' );
		location.href = u.toString();
	} );
	$( 'reset' ).addEventListener( 'click', () => setMode( 'hero' ) );
	wireWipe();
}

/* ------------------------------------------------------------ compare wipe */
function wireWipe() {
	const knob = $( 'knob' );
	const bar = $( 'bar' );
	let drag = false;
	const set = ( clientX ) => {
		const r = frameEl.getBoundingClientRect();
		const refW = parseFloat( frameEl.style.getPropertyValue( '--refW' ) ) || r.width;
		const refL = parseFloat( frameEl.style.getPropertyValue( '--refL' ) ) || 0;
		splitT = Math.max( 0, Math.min( 1, ( clientX - r.left - refL ) / refW ) );
		placeSplit();
	};
	const start = ( e ) => {
		if ( ! frameEl.classList.contains( 'cmp' ) ) return;
		drag = true; set( e.clientX ); e.preventDefault(); e.stopPropagation();
	};
	knob.addEventListener( 'pointerdown', start );
	bar.addEventListener( 'pointerdown', start );
	frameEl.addEventListener( 'pointerdown', ( e ) => {
		if ( ! frameEl.classList.contains( 'cmp' ) || mode !== 'hero' ) return;
		drag = true; set( e.clientX );
	} );
	addEventListener( 'pointermove', ( e ) => { if ( drag ) set( e.clientX ); } );
	addEventListener( 'pointerup', () => { drag = false; } );
	addEventListener( 'keydown', ( e ) => {
		if ( ! frameEl.classList.contains( 'cmp' ) ) return;
		if ( e.key === '[' ) splitT = Math.max( 0, splitT - 0.02 );
		else if ( e.key === ']' ) splitT = Math.min( 1, splitT + 0.02 );
		else return;
		placeSplit();
	} );
}

/* --------------------------------------------------------------- fly mode */
/* Drag to look, wheel to dolly along the view axis, WASD / arrows to move,
   space and C for up and down, shift to sprint. Deliberately hand-rolled so
   the wheel dollies the camera rather than cropping the lens.            */
function makeFlyControls( cam, dom, opts = null ) {

	/* On the page these controls are live the whole time the hero is on
	 * screen, which means they share the keyboard and the wheel with a
	 * document. `opts.allow` is the gate - no flying while the hero is
	 * scrolled away - the wheel is left to the page, and `opts.bounds`
	 * keeps a walk from wandering off the modelled block. */
	const gate = () => {
		if ( ! enabled ) return false;
		if ( opts && opts.allow && ! opts.allow() ) return false;
		const a = document.activeElement;
		return ! ( a && ( /^(INPUT|SELECT|TEXTAREA|BUTTON|A)$/.test( a.tagName ) || a.isContentEditable ) );
	};

	const keys = new Set();
	let yaw = 0, pitch = 0, dragging = false, px = 0, py = 0;
	let dolly = 0, enabled = false;
	const euler = new THREE.Euler( 0, 0, 0, 'YXZ' );
	const dir = new THREE.Vector3();
	const SPEED = ( opts && opts.speed ) || 16;

	const sync = () => {
		euler.setFromQuaternion( cam.quaternion, 'YXZ' );
		yaw = euler.y; pitch = euler.x;
	};

	/* `opts.freeLook`: while it holds (a visitor walking), the view follows
	 * the mouse with no button held, as in any first-person walk (user,
	 * 2026-11-25: "when I walk I shouldn't have to hold to turn") - and the
	 * cursor never goes away (owner, 2026-11-26: "the mouse must never
	 * disappear while I walk"), so this is not Pointer Lock. A visible
	 * cursor stops at the edge of the window, so resting it near the left
	 * or right edge keeps the turn going. A pen or a finger keeps the drag. */
	const freeLook = () => !! ( opts && opts.freeLook && opts.freeLook() );
	const LOOK_RATE = 0.0026;          // radians per pixel
	const EDGE = 0.06;                 // fraction of the width that turns on its own
	const EDGE_RATE = 1.4;             // radians a second, right at the edge
	let hoverX = - 1;                  // pointer across the frame, 0..1; -1 = not over it
	const look = ( dx, dy ) => {
		yaw -= dx * LOOK_RATE;
		pitch -= dy * LOOK_RATE;
		pitch = Math.max( - 1.45, Math.min( 1.45, pitch ) );
		cam.quaternion.setFromEuler( euler.set( pitch, yaw, 0, 'YXZ' ) );
	};
	const down = ( e ) => {
		if ( ! enabled || e.button !== 0 ) return;
		if ( e.pointerType === 'mouse' && freeLook() ) return;
		/* ...and somebody else may want the drag. Looking straight down at
		 * a plan, turning the camera on the spot is not what a pointer
		 * dragged across it means - sliding the storey along is - so the
		 * floor view takes the drag and leaves the keys here. */
		if ( opts && opts.drag && ! opts.drag() ) return;
		dragging = true; px = e.clientX; py = e.clientY;
		dom.setPointerCapture( e.pointerId );
	};
	const move = ( e ) => {
		if ( e.pointerType === 'mouse' && freeLook() && ! dragging ) {
			const r = dom.getBoundingClientRect();
			hoverX = r.width ? ( e.clientX - r.left ) / r.width : - 1;
			if ( enabled ) look( e.movementX || 0, e.movementY || 0 );
			return;
		}
		hoverX = - 1;
		if ( ! dragging ) return;
		look( e.clientX - px, e.clientY - py );
		px = e.clientX; py = e.clientY;
	};
	const up = ( e ) => {
		dragging = false;
		if ( dom.hasPointerCapture && dom.hasPointerCapture( e.pointerId ) )
			dom.releasePointerCapture( e.pointerId );
	};
	const wheel = ( e ) => {
		if ( ! enabled || ( opts && opts.wheel === false ) ) return;
		e.preventDefault();
		dolly -= e.deltaY * ( e.shiftKey ? 0.004 : 0.02 );
	};
	const kd = ( e ) => {
		if ( ! gate() ) return;
		if ( /^(Arrow|Key[WASDQEC]|Space|Shift)/.test( e.code ) ) e.preventDefault();
		keys.add( e.code );
	};
	const ku = ( e ) => keys.delete( e.code );

	dom.addEventListener( 'pointerdown', down );
	dom.addEventListener( 'pointermove', move );
	dom.addEventListener( 'pointerleave', () => { hoverX = - 1; } );
	addEventListener( 'pointerup', up );
	dom.addEventListener( 'wheel', wheel, { passive: false } );
	addEventListener( 'keydown', kd );
	addEventListener( 'keyup', ku );

	return {
		set enabled( v ) { enabled = v; if ( v ) sync(); else keys.clear(); },
		get enabled() { return enabled; },
		// the hero rail moves the camera under these controls; whoever grabs
		// it has to start from where it is pointing, not where it was left
		sync,
		/* ...and the drag is theirs, so whoever else wants to write the
		 * camera's rotation - the walk, which lays a gait's roll and nod
		 * over it - has to read the two angles the drag is holding. */
		get look() { return { yaw, pitch }; },
		update( dt ) {
			if ( ! enabled ) return;
			// a cursor parked at the edge of the window keeps the walk turning
			if ( freeLook() && hoverX >= 0 ) {
				const t = hoverX < EDGE ? hoverX / EDGE - 1 : hoverX > 1 - EDGE ? ( hoverX - 1 + EDGE ) / EDGE : 0;
				if ( t ) look( ( t * EDGE_RATE * dt ) / LOOK_RATE, 0 );
			}
			const shift = keys.has( 'ShiftLeft' ) || keys.has( 'ShiftRight' );
			const fast = shift ? 3.4 : 1;
			const s = SPEED * fast * dt;
			const f = ( keys.has( 'KeyW' ) || keys.has( 'ArrowUp' ) ? 1 : 0 )
				- ( keys.has( 'KeyS' ) || keys.has( 'ArrowDown' ) ? 1 : 0 );
			const r = ( keys.has( 'KeyD' ) || keys.has( 'ArrowRight' ) ? 1 : 0 )
				- ( keys.has( 'KeyA' ) || keys.has( 'ArrowLeft' ) ? 1 : 0 );
			const u = ( keys.has( 'Space' ) || keys.has( 'KeyE' ) ? 1 : 0 )
				- ( keys.has( 'KeyC' ) || keys.has( 'KeyQ' ) ? 1 : 0 );
			/* Inside a flat these three keys are a person's legs rather
			 * than a camera's thrusters, and the walk answers for where
			 * the camera ends up - including the height, which is why
			 * space and C go nowhere in there: a visitor standing in a
			 * bedroom cannot rise through the ceiling. */
			if ( opts && opts.walk && opts.walk( dt, f, r, shift, keys ) ) { dolly = 0; return; }
			if ( f ) { cam.getWorldDirection( dir ); cam.position.addScaledVector( dir, f * s ); }
			if ( r ) {
				cam.getWorldDirection( dir );
				dir.cross( cam.up ).normalize();
				cam.position.addScaledVector( dir, r * s );
			}
			if ( u ) cam.position.y += u * s;
			if ( dolly ) {
				cam.getWorldDirection( dir );
				cam.position.addScaledVector( dir, dolly * ( 1 + Math.abs( dolly ) ) );
				dolly *= 0.0;
			}
			cam.position.y = Math.max( 0.4, cam.position.y );
		},
	};

}

function tween( dur, delay, update, done ) {
	tweens.push( { t0: null, dur, delay, update, done } );
}

/* A compile holds the frame loop (see `compileInto`): the picture stands
 * still, and a flight that went on in the meantime would come back a jump
 * further on. So on a walk (the walk up to a street door, a room dive) the
 * time a compile holds is not flight time - every tween already under way
 * has its start moved on by it, and the flight resumes from the frame the
 * visitor last saw. Off a walk the timing is as it always was. */
let tweenAt = 0;
function updateTweens() {
	const now = performance.now();
	const held = compiling && bwOn && tweenAt ? now - tweenAt : 0;
	tweenAt = now;
	for ( let i = tweens.length - 1; i >= 0; i -- ) {
		const tw = tweens[ i ];
		if ( tw.t0 === null ) tw.t0 = now;
		else if ( held ) tw.t0 += held;
		const t = Math.min( 1, Math.max( 0, ( now - tw.t0 - tw.delay ) / tw.dur ) );
		tw.update( t );
		if ( t >= 1 ) { tweens.splice( i, 1 ); if ( tw.done ) tw.done(); }
	}
}

/* the cut: the plane sweeps from where it is to `to` */
function animateSlice( plane, to, dur, delay, done ) {
	const from = plane.constant;
	tween( dur, delay, ( t ) => {
		plane.constant = from + ( to - from ) * easeInOut( t );
		shadowDirty();
	}, done );
}

/* The camera flight. A quadratic Bezier through a control point high over
 * the street end of the path: the camera cranes up first, then glides in
 * and settles, rather than cutting across the city in a straight line.
 * Orientation is slerped, and the field of view and the shift lens ease
 * between the two shots with the same curve, so the zoom and the tilt of
 * the image arrive together. */
function flyCamera( to, dur, delay, done ) {
	const p0 = camera.position.clone(), q0 = camera.quaternion.clone();
	const fov0 = camera.fov, shift0 = camera.lensShift, pan0 = camera.lensPan;
	const p1 = to.p, q1 = to.q;
	/* BOTH halves of the lens, not just the rise. The rail does not park
	 * its shot with HERO_SHIFT - it solves the shift and the pan per frame
	 * so the block's corner stays pinned in the window - so a flight back
	 * onto it has to arrive on the numbers the pin is about to ask for. It
	 * used to ease the shift to HERO_SHIFT instead, 0.34 of the frustum,
	 * and `railPin` then put it back in one frame: the whole picture slid
	 * up over four seconds and snapped down on arrival. */
	const pan1 = to.pan === undefined ? 0 : to.pan;
	const street = sceneNo === 2 ? p0 : p1;        // whichever end is the street shot
	const other = street === p0 ? p1 : p0;
	/* The crane's own lift. It is there to carry the shot OVER the roof on
	 * the way to the flat; a shot that ends above the roof already does not
	 * want it, and lifting past the end point makes the camera rise through
	 * its own target and sink back onto it - which, at the end of a long
	 * move under a quintic ease, is a camera that appears to stick. */
	const lift = to.lift === undefined ? 9.0 : to.lift;
	const ease = to.ease || smoother;
	const ctrl = new THREE.Vector3(
		( p0.x + p1.x ) * 0.5,
		Math.max( p0.y, p1.y ) + lift,
		street.z * 0.7 + other.z * 0.3 );
	const a = new THREE.Vector3(), b = new THREE.Vector3();
	tween( dur, delay, ( t ) => {
		const e = ease( t );
		a.copy( p0 ).lerp( ctrl, e );
		b.copy( ctrl ).lerp( p1, e );
		camera.position.copy( a ).lerp( b, e );
		camera.quaternion.slerpQuaternions( q0, q1, e );
		camera.fov = fov0 + ( to.fov - fov0 ) * e;
		camera.lensShift = shift0 + ( to.shift - shift0 ) * e;
		camera.lensPan = pan0 + ( pan1 - pan0 ) * e;
		camera.updateProjectionMatrix();
	}, done );
}

/* ------------------------------------------------------- the floor step
 * How long a click on a storey takes, in and out again, in milliseconds.
 *
 * ONE number for the whole step: the camera leaving the street, the cut
 * taking the building off the storey, the storeys over it coming away, and
 * the wait before the plan stops being a render. They were tuned apart -
 * 3400 for the crane, 3400 for the sweep, 1300 for the wait - and tuning
 * them apart is how you get a camera that has landed over a building still
 * opening underneath it. Cut from one number they arrive together however
 * fast it is set.
 *
 * The ease is `easeInOut` rather than the quintic `smoother` the long tour
 * crane uses: a quintic spends its first tenth almost motionless, which at
 * this length is most of the move.
 *
 * The tour's own flight into the show flat is NOT this - that one is a long
 * crane over the roof on purpose, and keeps its own seconds. */
const FLOOR_IN = 1200;

/* `lp:scene` is announced from inside `setScene`, BEFORE the crane is built,
 * and the page answers it by telling the scene how much of the frame it is
 * covering. `setInset` must not re-shoot the camera in that window: it did,
 * which parked the camera on the destination, and `flyCamera` then captured
 * that as its starting point and had nothing left to fly. There is no tween
 * yet to test for, so the flag says it instead. */
let sceneSettling = false;

function setScene( n, animate = true, floor = topFloor(), view = 'hero' ) {
	/* Scene 2 is the real building's levels now - see `lvSetScene`. Only a
	 * street that is already the street falls through to the old path,
	 * which is what settles the boot's first `setScene( 1 )`. */
	if ( FLAT_GONE ) {
		const r = lvSetScene( n, animate, floor, view );
		if ( r !== null || n === 2 ) return r;
	}
	sceneSettling = true;
	try { return setSceneNow( n, animate, floor, view ); }
	/* ...and whoever has the camera is settled here rather than left to
	 * `setMode`. Several of the scene's paths are a flight with the mode
	 * set in its own callback, and between the two the street would still
	 * be holding the keys it is not allowed to have. */
	finally { sceneSettling = false; flyApply(); }
}

function setSceneNow( n, animate, floor, view ) {
	const prev = sceneNo, prevFloor = sceneFloor, prevView = scene2View;
	// the hover borrows the flat and the x-ray; both go back before a scene
	// change, or the show flat would open at whatever storey was last lit
	floorReset();
	sceneNo = n;
	/* Coming back out keeps the storey it is leaving: the building closes
	 * over the flat where the flat is standing, and only then does the flat
	 * go away. Setting it here would drop both a storey mid-sweep. */
	if ( n === 2 ) sceneFloor = Math.max( 2, Math.min( topFloor(), floor | 0 ) );
	planStepReset();                 // the floor view always opens on the corner
	if ( n === 2 ) {
		scene2View = view;
		if ( view === 'plan' ) setPlanUp();
		/* The storey stays a building while the camera is leaving the
		 * street and the cut is still travelling down it; it becomes a
		 * drawing on the way up. */
		planHold = ( view === 'plan' && animate ) ? PLAN_HOLD : 0;
	}
	placeFlat();
	announce( 'scene', { scene: n, floor: sceneFloor,
		view: n === 2 ? scene2View : 'street' } );
	if ( ! ( n === 2 && scene2View === 'plan' ) )
		announce( 'planbadge', { badges: [], on: false } );
	if ( n === 2 && scene2View === 'plan' ) announcePlan();
	// ...and that no flat is open, so the page puts its type cards back
	planFocusTell();
	roomTell();
	roomDotTell();
	invalidate();
	shadowDirty();
	if ( n === 2 ) prepareScene2();
	$( 's_1' ).setAttribute( 'aria-pressed', String( n === 1 ) );
	$( 's_2' ).setAttribute( 'aria-pressed', String( n === 2 ) );
	$( 'sub' ).textContent = n === 1
		? 'Street · the solved shot'
		: sceneFloor >= topFloor() ? 'Show flat · top floor, corner'
			: `Show flat · floor ${ sceneFloor }, corner`;
	const cmp = $( 't_cmp' );
	cmp.disabled = ( n === 2 );
	$( 'm_row' ).hidden =
		( n !== 2 || ! ( meta && meta.flat && meta.flat.row ) );
	$( 'r_plan' ).hidden = ( n !== 2 );
	$( 'r_mirror' ).hidden = ( n !== 2 );
	$( 'r_hide' ).hidden = ( n !== 2 );
	if ( n !== 2 ) $( 't_hide' ).checked = false;
	if ( n !== 2 && planOverlay ) planOverlay.visible = false;
	else setPlan( $( 't_plan' ).checked );

	if ( ! groups.cut || ! animate ) {
		tweens.length = 0;
		cutPlane.constant = 1e4;           // the cut group is just hidden here
		towerPlane.constant = n === 2 ? towerCut( sceneFloor ) : 1e4;
		if ( groups.cut ) {
			groups.cut.visible = ( n === 1 );
			groups.flat.visible = ( n === 2 );
		}
		setCompare( n === 1 && cmp.checked );
		setMode( 'hero' );
		return;
	}
	/* Scene 2's two views, swapped on the same storey. The building is
	 * already open and the cut is already exactly where it belongs, so
	 * this is a camera move and nothing else - running the sweep again
	 * would close and re-open a storey that never shut. Without it the
	 * change fell through to the test below and CUT, which is what going
	 * from the floor view into the tour used to do. */
	if ( n === 2 && prev === 2 && sceneFloor === prevFloor && scene2View !== prevView ) {
		tweens.length = 0;
		/* The flat is handed back BEFORE the move rather than when it lands.
		 * `floorReset` at the top of this function has just taken it off
		 * the storey hover - which borrows the real group rather than a
		 * copy, and hides it on the way out - and the full path below only
		 * gives it back in the flight's own callback. Without this the
		 * tour flew into an empty storey. */
		if ( groups.flat ) groups.flat.visible = ! $( 't_hide' ).checked;
		const pose = scene2View === 'plan' ? planPose() : flatPose();
		pose.lift = 0;               // both ends are already over the storey
		flyCamera( pose, 2400, 0, () => setMode( 'hero' ) );
		return;
	}
	if ( n === prev && sceneFloor === prevFloor ) {
		if ( tweens.length === 0 ) setMode( 'hero' );
		return;
	}

	// One move: the camera flies while the cut sweeps. Going in, the roof
	// starts to open as the camera comes over it; coming back, the building
	// closes first and the camera glides down to the street. A click
	// mid-move just turns everything round from where it is.
	tweens.length = 0;
	controls.enabled = false;
	fly.enabled = EMBED;             // the page is always walkable
	mode = 'hero';
	for ( const k of [ 'hero', 'orbit', 'fly' ] )
		$( 'm_' + k ).setAttribute( 'aria-pressed', String( k === 'hero' ) );
	setCompare( false );
	if ( ! groups.cut.visible ) cutPlane.constant = cutBottom;
	if ( cutPlane.constant > cutTop ) cutPlane.constant = cutTop;
	groups.cut.visible = groups.flat.visible = true;
	/* The storeys standing over the one that was clicked. On the top floor
	 * there are none: `towerCut` parks the plane and the sweep is skipped
	 * altogether, so that shot is exactly what it always was. */
	const storeys = towerCut( sceneFloor ) < 1e4 || towerPlane.constant < 1e4;
	if ( storeys && towerPlane.constant > towerTop ) towerPlane.constant = towerTop;
	if ( n === 2 ) {
		const pose = scene2View === 'plan' ? planPose() : flatPose();
		flyCamera( pose, pose.dur || 4200, 0, () => {
			setMode( 'hero' );
			groups.flat.visible = ! $( 't_hide' ).checked;
		} );
		/* The cut starts on the click, not when the camera gets there. It
		 * used to wait two seconds, so the roof opened as the shot came over
		 * it - which reads well in a flythrough and reads as a dead button
		 * when you have just clicked a storey: the one thing a click has to
		 * do is answer at once. So the building begins to come apart from
		 * the street, and the camera arrives into a flat that is already
		 * open. The sweep is longer than it was for the same reason - it has
		 * the whole flight to spend now rather than the tail of it. */
		const cutDur = scene2View === 'plan' ? FLOOR_IN : 3400;
		animateSlice( cutPlane, cutBottom, cutDur, 0, () => { groups.cut.visible = false; } );
		// ...taken off by the same sweep, in the same seconds, so the
		// building opens as one movement rather than two
		if ( storeys ) animateSlice( towerPlane, towerCut( sceneFloor ), cutDur, 0 );
	} else {
		/* Out of the FLOOR view the step is the click in, run backwards:
		 * the same length and the same ease, so leaving a storey costs what
		 * opening it did. Out of the tour's show flat it is the long crane
		 * it always was. */
		const wasPlan = ( prev === 2 && prevView === 'plan' );
		const out = wasPlan ? FLOOR_IN : 4200;
		const cutDur = wasPlan ? FLOOR_IN : 2200;
		animateSlice( cutPlane, cutTop, cutDur, 0,
			() => { groups.flat.visible = false; cutPlane.constant = 1e4; } );
		/* The building closes first and the flat is taken away behind it, so
		 * the storey is never seen standing in the open air. */
		if ( storeys ) animateSlice( towerPlane, towerTop, cutDur, 0, () => {
			towerPlane.constant = 1e4;
			sceneFloor = topFloor();
			placeFlat();
		} );
		const back = heroPose();
		if ( wasPlan ) {
			/* No crane lift and no 800 ms wait. The floor view is already
			 * 50 m over the roof, so the lift only pushed the camera up
			 * through its own target and let it sink back - and the wait,
			 * plus the near-flat start of the quintic, was a second and
			 * three quarters of a frozen picture after the click. It leaves
			 * on the click now and comes straight down. */
			back.lift = 0;
			back.ease = easeInOut;
		}
		/* `keepRail`: the flight is aimed at the rail phase the visitor
		 * left the street on, so arriving must not wind that sweep back to
		 * its start. See `resetShot`. */
		flyCamera( back, out, wasPlan ? 0 : 800, () => {
			setMode( 'hero', true );
			setCompare( cmp.checked );
		} );
	}
}

/* The flat, and the sales plan laid on it, carried to the storey the scene
 * is open on. One offset for both: they are built on the top floor and move
 * down together. The hover's own copy is placed by `floorPlace`, which has
 * its own storey and is reset before this ever runs. */
function placeFlat() {
	const dy = floorDrop();
	if ( groups.flat ) groups.flat.position.y = dy;
	if ( planOverlay ) planOverlay.position.y = dy;
	planPlaceBox();                  // ...and the storey the drawing is fenced to
}

/* ------------------------------------------------------ one storey down
 * The build fits the show flat to the top floor and writes `scene_meta.json`
 * there, so every number in it - the flat's centre, its floor, the cut - is
 * measured on that storey. A lower one is the SAME flat moved down whole
 * storeys, so one offset carries the lot: the group the flat is drawn in,
 * the camera that frames it, and the plane that takes the building off it.
 * Zero on the top floor, so nothing about that shot moves. */
const topFloor = () => ( meta && meta.block && meta.block.floors )
	? meta.block.floors.n : 10;
function floorDrop( n = sceneFloor ) {
	const b = meta && meta.block && meta.block.floors;
	return ( b && n ) ? ( n - b.n ) * b.h : 0;
}
/* Where the storey cut stops. `cutBottom` is just under the top floor's
 * slab, which is where the pre-split cut already ends, so the same number
 * dropped by whole storeys is just under storey `n`'s. The top floor keeps
 * the plane parked: its cells are taken by `cutPlane` and the roof standing
 * behind the flat is part of that shot. */
const towerCut = ( n ) => n >= topFloor() ? 1e4 : cutBottom + floorDrop( n );

/* the flat, in the browser's frame, from the build's scene_meta.json */
function flatFrame() {
	const f = meta && meta.flat;
	const c = new THREE.Vector3( ...( f ? f.center : [ 10, 32, -95 ] ) );
	c.y += floorDrop();
	return {
		c,
		ex: new THREE.Vector3( ...( f ? f.ex : [ 1, 0, 0 ] ) ),
		ey: new THREE.Vector3( ...( f ? f.ey : [ 0, 0, -1 ] ) ),
	};
}

function orbitTarget() {
	if ( FLAT_GONE && sceneNo === 2 && lvOpen ) return lvCenter();
	return sceneNo === 2 ? flatFrame().c : siteCenter();
}

/* The middle of the real building in world metres (scene_meta.site.center,
 * written by the build) - the street's orbit target and fly bound. The old
 * block A's middle is only the fallback for a page with no meta. */
function siteCenter() {
	const c = meta && meta.site && meta.site.center;
	return c ? new THREE.Vector3( c[ 0 ], c[ 1 ], c[ 2 ] ) : new THREE.Vector3( 10, 17, -95 );
}

/* The opening shot of the real building, from scene_meta.site.hero (world
 * metres): a level camera turned to the target's bearing, and the rise of a
 * shift lens that puts the target on the frame's centre line, so verticals
 * stay vertical as they do in the architect's renders. Null with no meta. */
/* `?hero=<name>`: one of the opening shots the exterior review proposed
 * (scene_meta.site.hero_candidates - square_9m, front_eye, sw_corner_eye),
 * so the owner can compare them live against the rail. Exactly as that
 * report specifies: the candidate's eye and aim, a vertical field of view
 * of 2 atan( tan( hfov / 2 ) / aspect ) so `hfov` is held across the frame,
 * and its own lens shift and pan; on the page the rail sweeps about that
 * pose. The default (no `?hero=`) is untouched. */
const HERO_PICK = __q.get( 'hero' );
function heroCand() {
	const c = HERO_PICK && meta && meta.site && meta.site.hero_candidates && meta.site.hero_candidates[ HERO_PICK ];
	return c || null;
}
const candFov = ( c ) => 2 * Math.atan( Math.tan( c.hfov * Math.PI / 360 ) / frameAspect() ) * 180 / Math.PI;
function metaHero() {
	const hc = heroCand();
	if ( hc ) {
		const p = new THREE.Vector3( ...hc.eye ), at = new THREE.Vector3( ...hc.at );
		const tmp = new THREE.PerspectiveCamera();
		tmp.position.copy( p );
		tmp.lookAt( at.x, p.y, at.z );
		return { p, q: tmp.quaternion.clone(), fov: candFov( hc ), shift: hc.shift, pan: hc.pan, target: at };
	}
	const h = meta && meta.site && meta.site.hero;
	if ( ! h ) return null;
	const p = new THREE.Vector3( ...h.eye ), at = new THREE.Vector3( ...h.at );
	const tmp = new THREE.PerspectiveCamera();
	tmp.position.copy( p );
	tmp.lookAt( at.x, p.y, at.z );
	const run = Math.hypot( at.x - p.x, at.z - p.z );
	// ...and a fifth of the frame more, so the target sits above the middle
	// and the sky - not the foreground - takes the spare height
	const shift = Math.max( 0, Math.min( 1, ( at.y - p.y ) / run / Math.tan( FOV_Y * Math.PI / 360 ) + 0.2 ) );
	return { p, q: tmp.quaternion.clone(), fov: FOV_Y, shift, target: at };
}

/* `keepRail` is only for the flight back to the street. See `resetShot`. */
/* Who has the camera, and what the pointer is therefore for.
 *
 * On the page the fly controls are not a mode, they ARE the camera - with
 * one exception. THE STREET IS NOT A CAMERA: it is the solved shot, the
 * photograph the whole model was built to match, riding its own slow rail,
 * and the only thing a visitor has to do with the pointer there is click
 * the storey they want. Letting them drag it off that framing and walk
 * away down the road gives away the one picture the page sells with -
 * `?rail=` exists precisely because that shot is composed. So in scene 1
 * the drag and the keys are both off, and the cursor says so.
 *
 * Everywhere in scene 2 they stay live: the flat is something to look
 * round, the floor view slides under the drag, and inside a room they are
 * the visitor's legs. The lab keeps flying as a mode you switch into -
 * except inside a flat, where the dive's own `setMode` would otherwise
 * take the legs away the moment it landed. */
function flyApply() {
	if ( ! fly ) return;
	fly.enabled = EMBED
		? ( mode !== 'orbit' && sceneNo !== 1 )
		: ( mode === 'fly' || ( mode === 'hero' && roomFocus >= 0 ) || bwOn );
	embedCursor( false );
}

/* The pointer's own affordance. A grab cursor over a shot that cannot be
 * dragged is the one thing it must not be, so it follows whoever has the
 * camera: a grab where there is something to hold, and over the street a
 * pointer on the storeys that open and nothing at all on the sky. */
let cursorSaid = '';
function embedCursor( grabbing ) {
	if ( ! EMBED || ! renderer ) return;
	/* ...and `progress` while a clicked level is still on its way: the click
	 * has been taken, the level is not on screen until it is here. */
	/* ...and walking, the mouse turns the head with no button held, so
	 * there is nothing to grab: a plain crosshair, always on screen. */
	const want = lvWaiting ? 'progress' : ( fly && fly.enabled )
		? ( bwOn ? 'crosshair' : grabbing ? 'grabbing' : 'grab' )
		: ( ( floorHot || lvHotLevel || bwHot ) ? 'pointer' : 'default' );
	if ( want === cursorSaid ) return;
	cursorSaid = want;
	renderer.domElement.style.cursor = want;
}

function setMode( next, keepRail = false ) {
	mode = next;
	invalidate();
	announce( 'mode', { mode: next, scene: sceneNo } );
	for ( const k of [ 'hero', 'top', 'row', 'orbit', 'fly' ] )
		$( 'm_' + k ).setAttribute( 'aria-pressed', String( k === next ) );
	// Hero is a locked preset in BOTH scenes. It used to stay orbitable in the
	// flat, and OrbitControls' damping then walked the camera round to the far
	// side, where the rooms read mirrored and the kitchen looked like it was in
	// the wrong half of the plan. Press Orbit to move.
	controls.enabled = ( next === 'orbit' );
	flyApply();
	camera.lensShift = ( next === 'hero' && sceneNo === 1 ) ? LENS_RISE : 0;
	if ( next === 'top' ) topShot();
	else if ( next === 'row' ) rowShot();
	else if ( next === 'hero' ) resetShot( keepRail );
	else {
		if ( next === 'orbit' ) {
			// start the orbit from wherever hero left the camera, so pressing
			// Orbit never jumps the shot
			controls.target.copy( orbitTarget() );
			controls.update();
		}
		camera.updateProjectionMatrix();
	}
	$( 'hint' ).textContent = next === 'top'
		? 'Straight down on the flat. Turn on Reference plan to lay the sales plan on the floor.'
		: next === 'row'
		? 'All four flats of the top floor, down the line from the gable end.'
		: next === 'fly'
		? 'Drag to look, wheel to zoom, WASD to fly, space / C for height, shift to sprint.'
		: next === 'orbit'
			? 'Drag to orbit, wheel to zoom, right-drag to pan.'
			: sceneNo === 2
				? ( scene2View === 'plan'
					? 'The whole storey from above. Press Orbit to move around it.'
					: 'The sales-plan view. Press Orbit to move around the flat.' )
				: 'Drag the handle to wipe between the photograph and the render.';
}

/* The solved shot is a shift lens: the camera stays level and the frustum is
 * moved instead, so verticals stay vertical. `lensShift` lifts the frame,
 * `lensPan` slides it across, and both go straight onto the projection
 * matrix after three.js has built it, so the temporal jitter TRAA applies
 * underneath still works. */
function installLensShift( cam ) {
	const base = THREE.PerspectiveCamera.prototype.updateProjectionMatrix;
	cam.lensShift = LENS_RISE;
	cam.lensPan = 0;
	cam.updateProjectionMatrix = function () {
		base.call( this );
		this.projectionMatrix.elements[ 9 ] += this.lensShift;
		this.projectionMatrix.elements[ 8 ] -= this.lensPan;   // + pans the shot right
		this.projectionMatrixInverse.copy( this.projectionMatrix ).invert();
	};
}

/* Scene 2's shot: above the street corner, looking down into the opened flat
 * from the front left, so the two loggias sit nearest and the rooms read in
 * order behind them - the angle the sales render uses, mirrored to the
 * street side so the rest of the building never stands in the way. */
/* The two shots as poses: position, orientation, field of view, shift. */
function heroPose() {
	// the page's hero travels, and it carries its own lens (see railLens)
	if ( railOn() ) {
		const q = railPose( railT );
		return Object.assign( q, railLens( q.p, q.q ) );
	}
	const mh = metaHero();
	if ( mh ) return mh;
	const p = new THREE.Vector3( 0, EYE, - HERO_PUSH );
	const tmp = new THREE.PerspectiveCamera();
	tmp.position.copy( p );
	tmp.lookAt( 0, EYE, - HERO_PUSH - 1 );
	return { p, q: tmp.quaternion.clone(), fov: FOV_Y, shift: HERO_SHIFT,
		target: new THREE.Vector3( 10, 17, - 95 ) };
}

/* ------------------------------------------------------------- the rail
 * The landing page's camera is never parked. For as long as the hero is on
 * screen it circles the block - one way, then back, for ever - so the
 * building turns slowly in the frame instead of standing still in it.
 *
 * The path is a true circle around the middle of block A. The two poses the
 * user flew to and settled on give it everything else: the sector it runs
 * through, the eye level (stood RAIL_RISE higher than they were flown), and
 * the radius, which is the further of the two times RAIL_ZOOM. Without the
 * block's own numbers - no scene_meta - it falls back to a Bezier between
 * the two poses, bowed away from the building.
 *
 * The composition does not travel with the camera. The near corner of the
 * block is carried to the same point of the window at every phase: the AIM
 * does the gross work (the camera looks at that corner, turned left and
 * down by the angles that put it RAIL_PIN_X across and RAIL_PIN_Y down),
 * and the two lens pins trim the hundredth that is left. So the gap between
 * the type and the building, and the headroom over it, never change.
 *
 * It yields to the visitor. A drag, a key or the wheel stops it where it
 * is, and RAIL_IDLE later the camera eases back onto the rail and carries
 * on from the phase it was at. `?rail=0` parks it, `?rail=<secs>` sets how
 * long one leg takes, `?zoom=` stands it off, `?pin=` / `?pinx=` move the
 * corner in the frame. */
/* Both ends are the shots as flown, stood RAIL_RISE higher: the aim rises
 * with the camera, so the pitch is still the -6.8 and -6.4 degrees they were
 * flown at and only the eye level changes. */
const RAIL_RISE = 7.0;
const RAIL_A = { p: [ 10.91, 15.57 + RAIL_RISE, - 28.64 ], at: [ 6.57, 14.39 + RAIL_RISE, - 37.57 ] };
const RAIL_B = { p: [ 45.98, 16.14 + RAIL_RISE, - 57.3 ], at: [ 37.4, 15.02 + RAIL_RISE, - 62.31 ] };
const RAIL_SECS = + ( __q.get( 'rail' ) ?? 230 );  // one leg, seconds (owner 2026-11-26, picked with ?rail=: 230)
const RAIL_BOW = 26.0;       // metres the path bows away from the block, so
                             // the middle of the sweep still holds all of it
const RAIL_LIFT = 2.5;       // ...and rises over the middle of the sweep
const RAIL_SWING = 0.0;      // degrees the aim is turned left (building right)
/* How far down the window the top of the block's near corner sits, as a
 * fraction of the height. It was 120 px; the user asked for the building a
 * tenth of the frame lower, and a fraction keeps that proportion whatever
 * shape the window is. `?pin=0.16` puts it back where it was. */
const RAIL_PIN_Y = + ( __q.get( 'pin' ) ?? 0.26 );
/* ...and where across the window that corner stands, as a fraction of the
 * width. Pinning it is what keeps the gap between the type and the building
 * the same all the way round: the camera orbits, the composition does not. */
/* 0.52 -> 0.46 -> 0.56 -> 0.66 -> 0.61 -> 0.55 (user, 2026-11-25 and again 2026-11-26:
 * the building sat too near the headline; "move it right by 10%"; then
 * "too much, a little left", and at 0.61 the front ran off the right). */
const RAIL_PIN_X = + ( __q.get( 'pinx' ) ?? 0.55 );
/* ...and it stays there the whole sweep: the corner must never pass under
 * the headline (owner, 2026-11-26). `?pinxend=` lets it drift. */
const RAIL_PIN_X_END = + ( __q.get( 'pinxend' ) ?? RAIL_PIN_X );
let railPinX = RAIL_PIN_X;
const RAIL_PAUSE = 1200;     // ms held still at each end - and at full size
const RAIL_IDLE = 9000;      // ms after a drag before it picks up again
const RAIL_REJOIN = 2600;    // ms easing back onto the rail

const _rA = new THREE.Vector3( ...RAIL_A.p ), _rB = new THREE.Vector3( ...RAIL_B.p );
const _rAat = new THREE.Vector3( ...RAIL_A.at ), _rBat = new THREE.Vector3( ...RAIL_B.at );
/* The control point: out along the chord's normal, on the far side from
 * whatever the two shots are aimed at, and lifted. */
const _rC = ( () => {
	const mid = _rA.clone().lerp( _rB, 0.5 );
	const aim = _rAat.clone().lerp( _rBat, 0.5 ).sub( mid );
	const d = _rB.clone().sub( _rA ); d.y = 0;
	const n = new THREE.Vector3( - d.z, 0, d.x ).normalize();
	if ( n.dot( aim ) > 0 ) n.negate();
	return mid.addScaledVector( n, RAIL_BOW ).setY( mid.y + RAIL_LIFT );
} )();
const _rp = new THREE.Vector3(), _rt = new THREE.Vector3();
const _rcam = new THREE.PerspectiveCamera();
let railT = 0, railDir = 1, railHoldUntil = 0, railTouchAt = - 1e9, railBusy = false;
const railOn = () => EMBED && RAIL_SECS > 0;

/* The building has to keep the same headroom the whole way round, so the
 * top of its near corner is pinned RAIL_PIN_Y of the height under the top edge of the
 * window. The vertical lens shift does it - the frustum moves, the camera
 * does not - exactly as HERO_SHIFT does for the parked shot, except solved
 * per frame: project the corner with no shift, then shift by the difference.
 * `?pin=0` pins it to the very top edge, `?pin=` anything else moves it. */
const _pinV = new THREE.Vector3();
const _aimD = new THREE.Vector3(), _aimR = new THREE.Vector3();
const _UP = new THREE.Vector3( 0, 1, 0 );

/* Where the camera looks from `p`: at the block's near corner, turned left
 * and down by exactly the angles that carry the corner to the place the
 * frame wants it - RAIL_PIN_X across, RAIL_PIN_Y down. Doing it with the
 * aim rather than with the lens is what keeps the frustum nearly on axis:
 * aiming at the middle of the block instead needed a lens pan of 0.73 and
 * the shot read as a shifted, skewed thing. The pins then trim the hundredth
 * that is left. */
/* The corner the frame holds: on the old sweep the block's near corner;
 * along the front, whichever top corner of the building stands furthest
 * LEFT as seen from where the camera is - so nothing of it ever passes
 * under the headline, from one end of the sweep to the other. */
let _roofPts = null;
const _rcD = new THREE.Vector3(), _rcR = new THREE.Vector3(), _rcQ = new THREE.Vector3(), _rcOut = [ 0, 0, 0 ];
function railCorner( p ) {
	const c = meta && meta.block && meta.block.corner;
	if ( ! RAIL_FRONT || ! c || ! meta.blocks || ! meta.frame ) return c;
	if ( ! _roofPts ) {
		const { origin: o, ex, ey } = meta.frame;
		_roofPts = [];
		for ( const b of meta.blocks ) for ( const [ x, y ] of b.footprint )
			_roofPts.push( new THREE.Vector3( o[ 0 ] + ex[ 0 ] * x + ey[ 0 ] * y, b.parapet_z, o[ 2 ] + ex[ 2 ] * x + ey[ 2 ] * y ) );
	}
	const C = meta.block.center;
	_rcD.set( C[ 0 ] - p.x, 0, C[ 2 ] - p.z ).normalize();
	_rcR.copy( _rcD ).cross( _UP );
	let best = null, bx = Infinity;
	for ( const q of _roofPts ) {
		_rcQ.copy( q ).sub( p );
		const fwd = _rcQ.dot( _rcD );
		if ( fwd <= 0 ) continue;
		const x = _rcQ.dot( _rcR ) / fwd;
		if ( x < bx ) { bx = x; best = q; }
	}
	if ( ! best ) return c;
	_rcOut[ 0 ] = best.x; _rcOut[ 1 ] = best.y; _rcOut[ 2 ] = best.z;
	return _rcOut;
}

/* Both corners in the window, wherever the camera is (owner, 2026-11-26:
 * "in this position the house's right corner must show too"). From the
 * street the whole 83 m front does not fit between the headline and the
 * right edge, so where it does not, the camera backs straight away from the
 * building's middle - and rises as it goes, RAIL_FIT_RISE m a metre, over the roofs across the
 * street (15-32 m; it is never lower than 33 m out there) - just as far as
 * it takes. Bisected, so the distance changes smoothly along the sweep. */
const RAIL_FIT_R = + ( __q.get( 'fitr' ) ?? 0.95 );   // NDC: the building's right edge no further than 97.5% across
const RAIL_FIT_RISE = + ( __q.get( 'fitrise' ) ?? 0.5 );
const _fitP = new THREE.Vector3(), _fitT = new THREE.Vector3(), _fitQ = new THREE.Vector3();
function railFits( p ) {
	railAim( p, _fitT );
	_plcam.position.copy( p );
	_plcam.up.set( 0, 1, 0 );
	_plcam.lookAt( _fitT );
	_plcam.fov = FOV_Y;
	_plcam.aspect = frameAspect();
	_plcam.lensShift = 0; _plcam.lensPan = 0;
	_plcam.updateProjectionMatrix();
	_plcam.updateMatrixWorld( true );
	_plcam.matrixWorldInverse.copy( _plcam.matrixWorld ).invert();
	for ( const q of _roofPts ) {
		_fitQ.copy( q ).project( _plcam );
		if ( _fitQ.z < 1 && ( _fitQ.x > RAIL_FIT_R || _fitQ.y > 0.97 ) ) return false;
	}
	return true;
}
function railFit( p, orb ) {
	railCorner( p );                       // builds _roofPts on first use
	if ( ! _roofPts || ! orb.out ) return p;
	if ( railFits( p ) ) return p;
	// straight away from the building's middle: at the ends that is out along the side streets, not over the roofs
	orb.out.set( p.x - orb.C.x, 0, p.z - orb.C.z ).normalize();
	const at = ( d ) => _fitP.copy( p ).addScaledVector( orb.out, d ).setY( p.y + RAIL_FIT_RISE * d );
	let lo = 0, hi = 160;
	if ( railFits( at( hi ) ) ) for ( let i = 0; i < 18; i ++ ) {
		const mid = ( lo + hi ) / 2;
		if ( railFits( at( mid ) ) ) hi = mid; else lo = mid;
	}
	return p.copy( at( hi ) );
}

function railAim( p, out ) {
	const c = railCorner( p );
	if ( ! c ) return out;
	const wantY = 1 - 2 * RAIL_PIN_Y;
	const wantX = railPinX * 2 - 1;
	const ty = Math.tan( FOV_Y * Math.PI / 360 );
	_aimD.set( c[ 0 ], c[ 1 ], c[ 2 ] ).sub( p ).normalize();
	_aimD.applyAxisAngle( _UP, Math.atan( wantX * ty * frameAspect() ) );
	_aimR.copy( _aimD ).cross( _UP ).normalize();
	_aimD.applyAxisAngle( _aimR, - Math.atan( wantY * ty ) );
	return out.copy( p ).add( _aimD );
}

function railPin() {
	const hc = heroCand();
	if ( hc ) {
		camera.fov = candFov( hc );
		camera.lensShift = hc.shift;
		camera.lensPan = hc.pan;
		camera.updateProjectionMatrix();
		return;
	}
	const c = railCorner( camera.position );
	if ( ! c ) return;
	camera.lensShift = 0;
	camera.lensPan = 0;
	camera.updateProjectionMatrix();
	camera.updateMatrixWorld( true );
	camera.matrixWorldInverse.copy( camera.matrixWorld ).invert();
	const base = _pinV.set( c[ 0 ], c[ 1 ], c[ 2 ] ).project( camera );
	const wantY = 1 - 2 * RAIL_PIN_Y;
	const wantX = railPinX * 2 - 1;
	camera.lensShift = Math.max( - 1.2, Math.min( 1.2, base.y - wantY ) );
	camera.lensPan = Math.max( - 0.9, Math.min( 0.9, wantX - base.x ) );
	camera.updateProjectionMatrix();
}

/* ...and the same answer for a pose the camera is not standing at yet.
 * `railPin` solves the pin on the live camera, which is all the rail
 * itself needs; a flight BACK onto the rail has to know the shift and the
 * pan before it starts, so it can ease onto them instead of having them
 * dropped on it in the frame it lands. Same arithmetic, on a stand-in. */
const _plcam = new THREE.PerspectiveCamera();
function railLens( p, q ) {
	const hc = heroCand();
	if ( hc ) return { shift: hc.shift, pan: hc.pan };
	const c = railCorner( p );
	if ( ! c ) return { shift: HERO_SHIFT, pan: 0 };
	_plcam.position.copy( p );
	_plcam.quaternion.copy( q );
	_plcam.fov = FOV_Y;
	_plcam.aspect = frameAspect();
	_plcam.updateProjectionMatrix();
	_plcam.updateMatrixWorld( true );
	_plcam.matrixWorldInverse.copy( _plcam.matrixWorld ).invert();
	const base = _pinV.set( c[ 0 ], c[ 1 ], c[ 2 ] ).project( _plcam );
	return {
		shift: Math.max( - 1.2, Math.min( 1.2, base.y - ( 1 - 2 * RAIL_PIN_Y ) ) ),
		pan: Math.max( - 0.9, Math.min( 0.9, ( railPinX * 2 - 1 ) - base.x ) ),
	};
}

/* The sweep is a circle around the block, not a line past it: the two flown
 * shots give the sector it runs through and the eye level it runs at, the
 * radius is the further of the two stood off by RAIL_ZOOM so the whole
 * building is in the frame, and the camera looks at the middle of the mass.
 * Where the building then sits in the frame is not left to the aim - the two
 * pins put its corner at the same point of the window all the way round. */
const RAIL_ZOOM = + ( __q.get( 'zoom' ) ?? 0.82 );
const RAIL_FRONT = __q.get( 'railfront' ) !== '0';
// where the sweep ends, plan x, y and eye height: the opening shot mirrored to block B's end, raised so block B's near top is not cut (`?railend=x,y,h`)
const RAIL_FRONT_END = ( __q.get( 'railend' ) || '111,72,32' ).split( ',' ).map( Number );
const RAIL_FRONT_UP = + ( __q.get( 'railup' ) ?? 24 );   // metres the curve's middle handles are raised
let _orb = null;
function railOrbit() {
	const c = meta && meta.block && meta.block.center;
	if ( ! c ) return null;
	if ( _orb ) return _orb;
	const C = new THREE.Vector3( c[ 0 ], c[ 1 ], c[ 2 ] );
	const ang = ( p ) => Math.atan2( p.z - C.z, p.x - C.x );
	const rad = ( p ) => Math.hypot( p.x - C.x, p.z - C.z );
	/* The real building's two ends of the sweep come with it, from
	 * scene_meta.site.rail (the build writes them from the plan); RAIL_A/B
	 * were flown round the old photo-fitted block and only stand in when
	 * there is no meta. */
	const mr = meta && meta.site && meta.site.rail;
	if ( mr ) { _rA.set( ...mr.a ); _rB.set( ...mr.b ); }
	let a0 = ang( _rA ), a1 = ang( _rB );
	while ( a1 - a0 > Math.PI ) a1 -= 2 * Math.PI;      // the short way round
	while ( a0 - a1 > Math.PI ) a1 += 2 * Math.PI;
	_orb = { C, a0, a1,
		r: Math.max( rad( _rA ), rad( _rB ) ) * RAIL_ZOOM,
		y0: _rA.y, y1: _rB.y };
	/* The sweep opens on the front - the rail's end b, loggias and shops to the street -
	 * and turns on the way it always turned, round towards block B
	 * (owner, 2026-11-26: "building start with front side", and when it
	 * was run backwards from B to A, "you turn the camera the other way").
	 * `?railfront=0`: the old A -> B arc, opening on the end wall. */
	if ( RAIL_FRONT && meta.frame ) {
		_orb.a0 = _orb.a1 = a1;
		_orb.y0 = _orb.y1 = _rB.y;
		const { origin: o, ex, ey } = meta.frame, [ x, y, h ] = RAIL_FRONT_END;
		_orb.s = new THREE.Vector3( C.x + Math.cos( a1 ) * _orb.r, _rB.y, C.z + Math.sin( a1 ) * _orb.r );
		_orb.e = new THREE.Vector3( o[ 0 ] + ex[ 0 ] * x + ey[ 0 ] * y, h, o[ 2 ] + ex[ 2 ] * x + ey[ 2 ] * y );
		_orb.c1 = _orb.s.clone().lerp( _orb.e, 1 / 3 );
		_orb.c2 = _orb.s.clone().lerp( _orb.e, 2 / 3 );
		_orb.c1.y += RAIL_FRONT_UP; _orb.c2.y += RAIL_FRONT_UP;   // 3/4 of it at the middle
		_orb.out = new THREE.Vector3();                             // set per pose by railFit
		_orb.front = true;
	}
	return _orb;
}

function railPose( t ) {
	const tt = Math.min( 1, Math.max( 0, t ) ), e = smoother( tt ), u = 1 - e;
	railPinX = RAIL_FRONT ? RAIL_PIN_X + ( RAIL_PIN_X_END - RAIL_PIN_X ) * e : RAIL_PIN_X;
	const orb = railOrbit();
	const hc = heroCand();
	if ( hc && orb ) {
		/* The rail's own sweep - the same arc, the same seconds - turned so
		 * its middle is the candidate's eye: eye and aim both swing about
		 * the building's middle, the candidate's height and lens held. */
		const a = ( e - 0.5 ) * ( orb.a1 - orb.a0 ), ca = Math.cos( a ), sa = Math.sin( a );
		const rot = ( v, out ) => {
			const dx = v[ 0 ] - orb.C.x, dz = v[ 2 ] - orb.C.z;
			return out.set( orb.C.x + dx * ca - dz * sa, v[ 1 ], orb.C.z + dx * sa + dz * ca );
		};
		rot( hc.eye, _rp ); rot( hc.at, _rt );
		_rcam.position.copy( _rp );
		_rcam.up.set( 0, 1, 0 );
		_rcam.lookAt( _rt.x, _rp.y, _rt.z );
		return { p: _rp.clone(), q: _rcam.quaternion.clone(), fov: candFov( hc ), shift: hc.shift, target: _rt.clone() };
	}
	if ( orb ) {
		const a = orb.a0 + ( orb.a1 - orb.a0 ) * e;
		_rp.set( orb.C.x + Math.cos( a ) * orb.r,
			orb.y0 + ( orb.y1 - orb.y0 ) * e,
			orb.C.z + Math.sin( a ) * orb.r );
		/* From the front: one corner to the other. It starts on the opening
		 * shot off block A's end and ends on its mirror off block B's end
		 * (RAIL_FRONT_END), down the street - clear from plan y 50 to 75, the
		 * houses across it start at 78 - rising RAIL_FRONT_UP over the
		 * middle. It sets off to the right at once (owner, 2026-11-26: "when
		 * the turn starts the camera must start moving right straight
		 * away"): most of its speed from the first frame, not the quintic's
		 * slow start, and the first leg of the curve points along the
		 * street, not out from the building. */
		if ( orb.front ) {
			// mostly even: the quintic alone runs the middle at nearly twice the average speed
			const f = 0.8 * tt + 0.2 * e, g = 1 - f;
			_rp.copy( orb.s ).multiplyScalar( g * g * g )
				.addScaledVector( orb.c1, 3 * g * g * f )
				.addScaledVector( orb.c2, 3 * g * f * f )
				.addScaledVector( orb.e, f * f * f );
			railFit( _rp, orb );
		}
		railAim( _rp, _rt );
		_rcam.position.copy( _rp );
		_rcam.up.set( 0, 1, 0 );
		_rcam.lookAt( _rt );
		return { p: _rp.clone(), q: _rcam.quaternion.clone(),
			fov: FOV_Y, shift: HERO_SHIFT, target: _rt.clone() };
	}
	_rp.copy( _rA ).multiplyScalar( u * u )
		.addScaledVector( _rC, 2 * u * e )
		.addScaledVector( _rB, e * e );
	_rt.copy( _rAat ).lerp( _rBat, e );
	if ( RAIL_SWING ) {
		// turn the aim about the camera, so the subject slides across frame
		_rt.sub( _rp ).applyAxisAngle( _rcam.up.set( 0, 1, 0 ), RAIL_SWING * Math.PI / 180 ).add( _rp );
	}
	_rcam.position.copy( _rp );
	_rcam.up.set( 0, 1, 0 );
	_rcam.lookAt( _rt );
	return { p: _rp.clone(), q: _rcam.quaternion.clone(),
		fov: FOV_Y, shift: HERO_SHIFT, target: _rt.clone() };
}

/* the visitor has the camera: stop, and let the fly controls pick up the
 * orientation the rail left them with */
function railWake() {
	/* ...only where there is a visitor who CAN take it. In the street the
	 * drag and the keys are off (see `flyApply`), so a click on the sky
	 * used to stop the sweep dead for the nine seconds of `RAIL_IDLE` and
	 * then ease it back on - a composed shot freezing because somebody
	 * missed a storey. */
	if ( ! fly || ! fly.enabled ) return;
	railTouchAt = performance.now();
	if ( fly.sync ) fly.sync();
}

/* back onto the rail from wherever the visitor left the camera */
function railRejoin( to ) {
	const p0 = camera.position.clone(), q0 = camera.quaternion.clone();
	railBusy = true;
	const s0 = camera.lensShift, n0 = camera.lensPan;
	tween( RAIL_REJOIN, 0, ( t ) => {
		const e = smoother( t );
		camera.position.lerpVectors( p0, to.p, e );
		camera.quaternion.slerpQuaternions( q0, to.q, e );
		railPin();                        // what the pin wants here...
		camera.lensShift = s0 + ( camera.lensShift - s0 ) * e;   // ...eased into
		camera.lensPan = n0 + ( camera.lensPan - n0 ) * e;
		camera.updateProjectionMatrix();
	}, () => { railBusy = false; } );
}

function railStep( dt ) {
	if ( ! railOn() || railBusy || sceneNo !== 1 ) return;
	if ( ! flyAllowed || tweens.length ) return;       // scrolled away, or flying
	const now = performance.now();
	if ( now - railTouchAt < RAIL_IDLE ) return;       // the visitor has it
	const pose = railPose( railT );
	// off the rail (a drag, or just back from the flat): ease on first
	if ( camera.position.distanceToSquared( pose.p ) > 2.5e-3
		|| Math.abs( camera.quaternion.dot( pose.q ) ) < 0.99995 ) {
		railRejoin( pose );
		return;
	}
	if ( now < railHoldUntil ) return;                 // held at an end
	railT += dt / RAIL_SECS * railDir;
	/* An END is only an end if the sweep was heading for it. `railT <= 0`
	 * on its own is also TRUE on the very first frame, where `railT` is 0
	 * and `clock.getDelta()` returns 0 because that call is what starts the
	 * clock - so the rail "arrived" at the end it was standing on, held for
	 * RAIL_PAUSE, turned round, stepped the other way into the clamp, and
	 * held again: 2.4 seconds of a frozen hero at every load, measured, and
	 * paid for at the full still density because nothing had moved. */
	if ( ( railDir > 0 && railT >= 1 ) || ( railDir < 0 && railT <= 0 ) ) {
		railT = railDir > 0 ? 1 : 0;
		railDir = - railDir;
		railHoldUntil = now + RAIL_PAUSE;
	}
	const q = railPose( railT );
	camera.position.copy( q.p );
	camera.quaternion.copy( q.q );
	railPin();
	invalidate( SETTLE );
}

/* Scene 2's shot: above the street corner, looking down into the opened flat
 * from the front left, so the two loggias sit nearest and the rooms read in
 * order behind them - the angle the sales render uses, mirrored to the
 * street side so the rest of the building never stands in the way. */
function flatPose() {
	const { c, ex, ey } = flatFrame();
	// From the entrance side, the way the sales render looks at it: the
	// facade with its windows is the far wall and stands full height, the
	// entrance wall nearest the camera is the one cut low.
	// From the street side. The entrance side would be the render's own angle,
	// but the block's roof stands between the camera and the flat there. The
	// pitch is steep enough to look over the now full-height facade wall.
	const t = c.clone().addScaledVector( ey, 0.6 );
	const p = t.clone().addScaledVector( ex, - 5.0 ).addScaledVector( ey, - 8.0 );
	p.y += 15.0;
	const tmp = new THREE.PerspectiveCamera();
	tmp.position.copy( p );
	tmp.lookAt( t );
	return { p, q: tmp.quaternion.clone(), fov: 36, shift: 0, target: t };
}

/* Straight down on the WHOLE storey, the block lying across the frame.
 *
 * This is what clicking a storey on the building opens. The question a click
 * on floor 8 asks is "what is on floor 8", and the answer is the floor - now
 * eight flats, a line on the street and a line on the back - not one flat on
 * it. The close shot of the show flat is still what the tour button opens.
 *
 * The shot does NOT turn the block square to the frame. Looking straight down,
 * +Y says nothing about which way round the view sits, so the roll has to come
 * from somewhere - and taking it from the block's own axis would spin the
 * whole scene through the bearing on the way up. It is taken from the heading
 * the camera had on the street instead (`planUp`, caught once in `setScene`),
 * so the move is a pure pitch down: nothing rotates under you.
 *
 * `planUp` is caught ONCE and kept, not read off the camera here. This runs
 * again on arrival - `setMode( 'hero' )` ends every crane move and resets the
 * shot - and by then the camera points straight down and has no heading left
 * to flatten, so re-reading it fell back to the block's axis and the view
 * turned under you in the last frame of the move.
 *
 * The roll has to be in the QUATERNION as well as in `up`, because the crane
 * flies by slerping between poses and never calls lookAt. */
/* The page's furniture has moved, so the shot is framed again. The cards
 * taking more or less of the window moves where the arrows can stop as well
 * as where the shot sits, so this is a re-fit and not just a re-shoot.
 * Mid-flight there is nothing to re-fit yet - the pose is being flown to -
 * and the page still wants its arrow count. */
function uiRefit() {
	if ( sceneNo !== 2 || scene2View !== 'plan' ) return;
	if ( ! tweens.length && ! sceneSettling ) { planClamp(); invalidate(); }
	else announcePlan();
}

/* The numbers the floor view's framing is made of, gathered in one place:
 * the shot itself and the stops the arrows step through are both read off
 * them, and a second copy of this arithmetic is a copy that goes wrong the
 * first time the fov or the fit changes. */
const PLAN_FIT = 1.13;            // how far outside the fit the shot sits
const PLAN_DROP = 0.2;            // ...the most of the frame it may drop
const PLAN_FOOT = 78;             // ...the breathing room left at the foot
const PLAN_SILL = 3;              // ...and the hair it sits under the cards' line
/* ...and a last nudge DOWN the window, in CSS pixels, after everything
 * above has had its say. It is its own number because `PLAN_SILL` is not a
 * translation: the sill feeds the fit as well as the drop - a bigger one
 * leaves a shorter band for the storey's depth, which flies the camera up
 * and shrinks the plate, which pulls its top edge back towards the line it
 * was being pushed off. Measured: the first two pixels asked of the sill
 * arrived, the next two came out as nothing and the match stopped being a
 * translation at all. This one is applied after the clamp and feeds
 * nothing, so it moves the building down the window and does not move
 * anything else - not the scale, and not the stops the arrows walk, which
 * are read along the frame's right. */
const PLAN_NUDGE = 6;
/* `B` is the plate as a box in its own plan metres - { o (world, on the
 * floor), ex, ey, x0, x1, y0, y1 } - which the real building's levels give
 * (`lvFrameBox`); without one it is the old row, from `meta.flat`. With
 * `fitClear` the WHOLE plate is fitted into the part of the window the
 * page's cards leave clear, rather than run off the right for the arrows
 * to walk: one level of the real building is one L-shaped plate, and the
 * question a click on a storey asks is answered by all of it at once. */
function planFrame( B = ( FLAT_GONE && lvOpen ) ? lvFrameBox() : null ) {
	let ex, ey, o, x0, x1, y0, y1;
	if ( B ) {
		( { ex, ey, o, x0, x1, y0, y1 } = B );
		o = o.clone();
	} else {
		( { ex, ey } = flatFrame() );
		const f = meta && meta.flat;
		const b = meta && meta.block && meta.block.floors;
		x0 = 0; y0 = 0;
		x1 = ( f && f.row ) ? f.row.end : ( f ? f.size[ 0 ] : 11.5 );
		y1 = b ? b.depth : ( f ? f.size[ 1 ] : 8.4 );
		o = new THREE.Vector3( ...( f ? f.origin : [ 0, 32, 0 ] ) );
		o.y += floorDrop();
	}
	const len = x1 - x0, depth = y1 - y0;
	const t = o.clone().addScaledVector( ex, ( x0 + x1 ) * 0.5 ).addScaledVector( ey, ( y0 + y1 ) * 0.5 );
	const ar = frameAspect();
	const fov = 32;                       // long enough that the ends of the
	                                      // block do not splay in the corners
	const up = planUp.clone();
	/* Measured in the FRAME's own axes rather than along the building, so it
	 * frames whatever roll `planUp` ends up with - including a camera that
	 * was dragged off the street shot before the storey was clicked, where
	 * the block does not lie square and a 46.7 x 18 rectangle stood at an
	 * angle puts its corners over the edge. Looking straight down,
	 * right = forward x up with forward = -Y. */
	const right = new THREE.Vector3( - up.z, 0, up.x );
	const d = new THREE.Vector3();
	let halfH = 0, halfW = 0, loW = Infinity;
	for ( const [ a, c ] of [ [ x0, y0 ], [ x1, y0 ], [ x0, y1 ], [ x1, y1 ] ] ) {
		d.copy( o ).addScaledVector( ex, a ).addScaledVector( ey, c ).sub( t );
		halfH = Math.max( halfH, Math.abs( d.dot( up ) ) );
		halfW = Math.max( halfW, Math.abs( d.dot( right ) ) );
		loW = Math.min( loW, d.dot( right ) );         // the plan's left edge
	}
	/* ACROSS the frame the storey is framed to the whole window, as it always
	 * was, and the page's inset only slides it sideways until its left end
	 * sits against the cards. Fitting its LENGTH into the narrower band
	 * instead meant flying 27 m further up for the same storey, and a plan
	 * read at that distance is a plan nobody can read; the row running off
	 * the right is what the arrows are for. Only its depth answers to the
	 * page, below. */
	const tan = Math.tan( fov * Math.PI / 360 );
	const fw = frameEl.clientWidth || 1;
	const fh = frameEl.clientHeight || 1;
	/* A hair outside the fit rather than flush against it. At 1.02 the plate
	 * ran off the top and the bottom of the window at once and read as a
	 * texture; the margin is what lets it read as a cut-away object sitting
	 * IN the frame. */
	let h = Math.max( halfH, halfW / ar ) / tan * PLAN_FIT;
	/* ...or, for the whole plate, its width into what the cards leave. */
	if ( B && B.fitClear ) {
		const cw = Math.max( fw * 0.4, fw - Math.max( 0, Math.min( uiInset, fw * 0.55 ) ) );
		h = Math.max( h, halfW / ( ar * cw / fw ) / tan * PLAN_FIT );
	}
	/* ...and once the page has said where its cards begin, the storey's
	 * DEPTH is fitted to the strip between that line and the foot of the
	 * window rather than to the whole window, so the near wall stands clear
	 * of the bottom edge instead of running off it. `PLAN_FOOT` was what the
	 * camera hints took off the foot and it is breathing room now that they
	 * are gone. Across the frame nothing changes: the row runs
	 * off the right either way and the arrows walk it along. The floor is
	 * what keeps a very short window from flying up for the last 20 pixels
	 * of a plan nobody can read by then anyway.
	 *
	 * The plate's top edge goes on the cards' line, `PLAN_SILL` under it. It
	 * is three pixels and it is not a fudge: what the fit measures is the
	 * storey's outermost corner, which is a balcony rail, so a plate laid
	 * flush on the line puts its WALL a few pixels above it. Thirty was
	 * tried first and read as the building having slid down the window.
	 *
	 * It moves the building only. The corner label is the page's, laid on
	 * the counts' line by `placeFloorLabel`, and stays where it is. */
	const sill = uiTop > 0 ? uiTop + PLAN_SILL : 0;
	if ( sill > 0 ) {
		const band = Math.max( fh * 0.45, fh - sill - PLAN_FOOT );
		h = Math.max( h, halfH * fw / ( band * tan * ar ) );
	}
	const inset = Math.max( 0, Math.min( uiInset, fw * 0.55 ) );
	const perPx = 2 * ( h * tan * ar ) / fw;           // world metres per CSS pixel
	/* ...and then stood down the frame rather than centred in it, so the
	 * margin the fit just bought is all at the top. The storey's top edge
	 * goes on the line the cards start on: centred, it lands `topNow` down
	 * the frame, and the page has said where it wants it. Capped, so a
	 * window too short to hold both never pushes the plan off its own foot,
	 * and worked in pixels and converted once, so the shot reads the same at
	 * any size. */
	const topNow = fh / 2 - halfH / perPx;
	const drop = ( Math.max( 0, Math.min( sill - topNow, fh * PLAN_DROP ) )
		+ PLAN_NUDGE ) * perPx;
	let shift = 0;
	if ( inset > 0 ) {
		const leftNow = fw / 2 - halfW / perPx;        // where its left end lands centred
		shift = ( inset - leftNow ) * perPx;           // ...and how far right of that it has to go
	}
	/* What is left of the window once the cards have had their share: how
	 * much of the row a visitor can actually see at once, and therefore how
	 * far the arrows have anywhere to go. */
	const clear = ( fw - inset ) * perPx;
	/* Last, so that `halfH`, `halfW` and the fit above are all measured off
	 * the storey's own centre. The drop is along the frame's up, which is
	 * square to its right, so it moves nothing the arrows' stops are read
	 * from. */
	t.addScaledVector( up, drop );
	return { ex, ey, o, t, up, right, fov, tan, ar, h, len, depth,
		halfW, loW, shift, perPx, fw, inset, clear,
		hidden: Math.max( 0, 2 * halfW - clear ) };
}

function planPose( pan = planPanM ) {
	const F = planFrame();
	const { up, right, fov, h, shift } = F;
	const t = F.t;
	t.addScaledVector( right, - shift + pan );
	const p = t.clone();
	p.y += h;
	const tmp = new THREE.PerspectiveCamera();
	tmp.up.copy( up );
	tmp.position.copy( p );
	tmp.lookAt( t );
	/* No crane lift, a shorter ease and the sweep's own duration. The move
	 * is 68 m where the flat's is 20, and on the quintic ease the last
	 * quarter of it took a second and a half - with the building finished
	 * opening 800 ms before the camera stopped. It read as a shot that
	 * sticks at the end, because that is what it was. */
	return { p, q: tmp.quaternion.clone(), fov, shift: 0, target: t, up,
		lift: 0, ease: easeInOut, dur: FLOOR_IN };
}

/* ------------------------------------------------ stepping along the row
 * The floor view frames the whole storey at a scale a plan can be READ at
 * and then slides it sideways until its left end clears the page's cards,
 * so the far end of the row sits off the right of the window. The two
 * arrows under the hint bar walk it along: one stop per flat, the first of
 * them the corner unit the view already opens on, and the last wherever
 * the end of the row comes flush with the right of the window.
 *
 * It is a PAN and nothing else. The camera and its target move together
 * along the frame's own right, so the height, the roll and the scale of
 * the plan never change and nothing rotates under the visitor - only which
 * flats are under the window. Every frame of it is `planPose` again rather
 * than a remembered pair of poses, so a window resized mid-slide, or the
 * page changing its inset, re-frames underneath the move instead of
 * fighting it.
 * -------------------------------------------------------------------- */
let planPanM = 0;                 // how far along the row, in metres
let planStep = 0;                 // ...and which stop that is
let planTween = null;

/* Where the arrows can stop. One per unit of the row - `row.starts` comes
 * off the bay table in the build, so nothing here has to know how wide a
 * flat is - plus the end of the row, and never past the point where the
 * row runs out and the window would fill with roof. */
function planStops() {
	const F = planFrame();
	// the real building's plate is fitted whole: no row to walk
	const starts = FLAT_GONE ? [ 0 ]
		: ( ( meta && meta.flat && meta.flat.row && meta.flat.row.starts ) || [ 0 ] );
	const d = new THREE.Vector3();
	/* Each unit's near edge, as metres right of the plan's own left edge -
	 * which is what a pan of that many metres brings flush with the cards.
	 * SORTED rather than taken in unit order: `planUp` comes from the
	 * heading the camera had on the street, not from the building, so the
	 * row can run either way across the frame. Left to right is left to
	 * right whichever end the gable is at. */
	const at = starts.map( ( x ) => {
		d.copy( F.o ).addScaledVector( F.ex, x ).sub( F.t );
		return d.dot( F.right ) - F.loW;
	} ).sort( ( a, b ) => a - b );
	const stops = [ 0 ];
	const add = ( x ) => { if ( x - stops[ stops.length - 1 ] > 0.75 ) stops.push( x ); };
	for ( const x of at ) if ( x < F.hidden ) add( x );
	if ( F.hidden > 0.75 ) add( F.hidden );
	return stops;
}

// a second click lands on top of the first rather than queueing behind it
function planKillTween() {
	if ( planTween ) { const k = tweens.indexOf( planTween ); if ( k >= 0 ) tweens.splice( k, 1 ); }
	planTween = null;
}

/* Slide to a stop. Clamped at both ends, so an arrow can be held down
 * without the plan wandering off the row. */
function planStepTo( i, animate = true ) {
	if ( ! planPanOwns() ) return;
	const stops = planStops();
	planStep = Math.max( 0, Math.min( stops.length - 1, Math.round( i ) ) );
	const to = stops[ planStep ];
	const from = planPanM;
	planKillTween();
	planVel = 0;
	if ( ! animate || Math.abs( to - from ) < 1e-3 ) {
		planPanM = to;
		planShot();
	} else {
		tween( 620, 0, ( t ) => {
			planPanM = from + ( to - from ) * easeInOut( t );
			applyPose( planPose( planPanM ) );
		}, () => { planTween = null; planTell(); } );
		planTween = tweens[ tweens.length - 1 ];
	}
	planTell();
	invalidate();
}

/* An arrow, from wherever the drag has left the plan. Free sliding stops
 * between flats as often as on one, and from there `+1` can only sensibly
 * mean the next flat AHEAD - rounding to the nearest stop first would make
 * a forward arrow walk backwards whenever the plan had drifted a little
 * past one. */
function planStepBy( d ) {
	if ( ! planPanOwns() || ! d ) return;
	const stops = planStops();
	const eps = 0.3;
	let i;
	if ( d > 0 ) {
		i = stops.findIndex( ( x ) => x > planPanM + eps );
		if ( i < 0 ) i = stops.length - 1;
		i = Math.min( stops.length - 1, i + ( d - 1 ) );
	} else {
		for ( i = stops.length - 1; i > 0 && stops[ i ] >= planPanM - eps; i -- ) ;
		i = Math.max( 0, i + ( d + 1 ) );
	}
	planStepTo( i );
}

/* What the page's arrows need. `step` and `steps` are for anything that
 * wants to show a position; `atStart` / `atEnd` are what the greying out
 * is driven by, because with free sliding the plan is usually BETWEEN two
 * stops and an index cannot say whether there is any row left. */
let planSaid = '';
function planTell( force = false ) {
	const stops = planStops();
	const hi = stops[ stops.length - 1 ] || 0;
	// the stop the plan is nearest, for anything that counts flats
	let near = 0, best = Infinity;
	for ( let i = 0; i < stops.length; i ++ ) {
		const e = Math.abs( stops[ i ] - planPanM );
		if ( e < best ) { best = e; near = i; }
	}
	planStep = near;
	const detail = { step: near, steps: stops.length,
		atStart: planPanM <= 0.3, atEnd: planPanM >= hi - 0.3 };
	/* Only when something the page can SHOW has changed. A drag writes the
	 * pan sixty times a second and every announce is a DOM write at the
	 * other end. */
	const key = detail.step + '/' + detail.steps + ( detail.atStart ? 'S' : '' ) + ( detail.atEnd ? 'E' : '' );
	if ( ! force && key === planSaid ) return;
	planSaid = key;
	announce( 'plan', detail );
}
const announcePlan = () => planTell( true );

/* ------------------------------------------------------- free sliding
 * The arrows are the coarse control; the plan is also simply DRAGGABLE,
 * the way a slider with free mode on is. The storey follows the pointer
 * one to one while a finger is down - no snapping, it comes to rest
 * wherever it is let go - and on release it carries the speed it was let
 * go at and runs down under friction.
 *
 * Past either end it does not stop dead: it follows at a third of the
 * pointer, so the row visibly resists, and springs back to the end when
 * the pointer lifts. That rubber band is the whole of what tells a
 * visitor there is no more row, without a wall they cannot see.
 * -------------------------------------------------------------------- */
const PLAN_TAU = 0.26;            // seconds for the glide to lose 1/e of its speed
const PLAN_STOPV = 0.25;          // ...and the speed, in m/s, it is dead below
const PLAN_PULL = 0.34;           // how far past the end the pointer gets to drag
const PLAN_BACK = 9.0;            // ...and how hard it is pulled home again
let planDrag = null;              // { id, x, t } while a pointer is down
let planVel = 0;                  // metres a second along the row

/* The floor view owns the pointer, so the fly controls must not also turn
 * the camera with it. Both read this. */
const planDragOwns = () => sceneNo === 2 && scene2View === 'plan';
/* ...and who owns the ROW. The two are not the same thing once a flat has
 * been opened: the view is still the plan view, so the fly controls must
 * keep their hands off the drag, but the row no longer slides and the
 * arrows no longer step - the camera is parked on one unit and the only
 * way out is a click. */
const planPanOwns = () => planDragOwns() && planFocus < 0 && ! lvFocusK;

/* How far the row can go, and the rubber band past it. */
function planLimit() {
	return planStops()[ planStops().length - 1 ] || 0;
}
function planClampPan( x, soft ) {
	const hi = planLimit();
	if ( x < 0 ) return soft ? x * PLAN_PULL : 0;
	if ( x > hi ) return soft ? hi + ( x - hi ) * PLAN_PULL : hi;
	return x;
}

/* `x` is already the value wanted - the clamping is the caller's, because
 * the three callers want three different things from it: the drag wants
 * the soft one so the row can be strained past its end, the glide wants
 * the hard one so momentum stops there, and the spring home wants none at
 * all or it would arrive the instant it set off. */
function planSetPan( x ) {
	planPanM = x;
	applyPose( planPose( planPanM ) );
	planTell();
	invalidate();
}

/* Pointer down on the plan: the glide stops where it is and the pointer
 * takes it from there, which is what makes a slider feel caught rather
 * than wrestled. */
function planPointerDown( e ) {
	if ( ! planPanOwns() || e.button !== 0 || tweens.length ) return;
	planKillTween();
	planVel = 0;
	/* The pointer's own x and the pan it started from, not a running sum of
	 * deltas. Accumulating deltas means compressing an already-compressed
	 * value on every move, and the overshoot then saturates at about half a
	 * mouse-step whatever the visitor does - a soft wall rather than a band
	 * that gives the further it is pulled. */
	planDrag = { id: e.pointerId, x0: e.clientX, pan0: planPanM,
		x: e.clientX, t: performance.now() };
	try { renderer.domElement.setPointerCapture( e.pointerId ); } catch ( err ) {}
}

function planPointerMove( e ) {
	if ( ! planDrag || e.pointerId !== planDrag.id ) return;
	const perPx = planFrame().perPx;
	const now = performance.now();
	/* The content follows the pointer, so dragging LEFT walks the view
	 * further along the row - the pan is measured the other way round.
	 * Taken from where the drag STARTED, so the row is exactly under the
	 * finger it was grabbed with however far it has travelled. */
	const raw = planDrag.pan0 - ( e.clientX - planDrag.x0 ) * perPx;
	/* A rolling estimate rather than the last frame's: a pointer sampled at
	 * 240 Hz hands you a 4 ms gap whose speed is mostly noise, and a flick
	 * that ends on one slow sample would otherwise land dead. */
	const dt = Math.max( 1, now - planDrag.t ) / 1000;
	planVel = planVel * 0.6 + ( - ( e.clientX - planDrag.x ) * perPx / dt ) * 0.4;
	planDrag.x = e.clientX;
	planDrag.t = now;
	planSetPan( planClampPan( raw, true ) );
}

function planPointerUp( e ) {
	if ( ! planDrag || ( e && e.pointerId !== planDrag.id ) ) return;
	const id = planDrag.id;
	planDrag = null;
	try {
		const dom = renderer.domElement;
		if ( dom.hasPointerCapture && dom.hasPointerCapture( id ) ) dom.releasePointerCapture( id );
	} catch ( err ) {}
	invalidate();
}

/* The glide, and the spring home from past an end. Run off the frame loop
 * rather than the tween list, for the same reason the storey's opening is:
 * a tween in flight pauses the hero's rail. */
function planGlide( dt ) {
	if ( ! planPanOwns() || planDrag || tweens.length ) return;
	const hi = planLimit();
	const over = planPanM < 0 ? planPanM : ( planPanM > hi ? planPanM - hi : 0 );
	if ( over !== 0 ) {
		/* Home first: a spring and a glide at once fight each other. Set
		 * RAW, not clamped - clamping here is what would make the rubber
		 * band snap back in one frame instead of easing. */
		planVel = 0;
		const edge = over > 0 ? hi : 0;
		const x = planPanM - over * Math.min( 1, PLAN_BACK * dt );
		planSetPan( Math.abs( x - edge ) < 0.01 ? edge : x );
		return;
	}
	if ( Math.abs( planVel ) < PLAN_STOPV ) { planVel = 0; return; }
	planVel *= Math.exp( - dt / PLAN_TAU );
	const x = planPanM + planVel * dt;
	if ( x <= 0 || x >= hi ) planVel = 0;          // the end takes the speed out
	planSetPan( planClampPan( x, false ) );
}

/* Re-fit after the window has changed shape. A narrower window hides more
 * of the row and a wider one hides less, so the stops move under the view:
 * without this a visitor who widens the window at the far end of the row is
 * left looking past the end of it, with a greyed-out arrow for company. The
 * step is kept and its new metres taken, so the plan stays on the flat it
 * was on wherever that now is. */
function planClamp() {
	planPanM = planClampPan( planPanM, false );
	planShot();
	announcePlan();
}

/* Back to the corner. The floor view is entered fresh every time a storey
 * is clicked, and arriving part way along the row - where the last visit
 * left it - would open on a flat nobody asked for. */
function planStepReset() {
	planKillTween();
	planDrag = null;
	planVel = 0;
	planPanM = 0;
	planStep = 0;
	planSaid = '';
	planFocus = - 1;
	planFocusSaid = - 2;
	planHot = - 1;
	roomFocus = - 1;
	roomSaid = - 2;
	roomShellClear();
}

/* The one place the floor view's shot is applied, so everything that
 * re-shoots it - the end of every crane move through `setMode( 'hero' )`,
 * a resize, the page changing how much of the window it covers - lands on
 * whichever of the two shots the view is actually on. */
function planShot() {
	if ( FLAT_GONE ) return lvShot();
	// ...and a fourth: once a visitor has walked into a room, that is the
	// shot the floor view is on, and a resize has to put them back in it
	if ( roomFocus >= 0 ) return roomShot();
	applyPose( planFocus >= 0 ? planFocusPose( planFocus ) : planPose() );
}

/* ------------------------------------------------- opening one flat
 * The third step. The floor view is a drawing of eight flats with the one
 * under the pointer furnished; clicking that flat is how a visitor says
 * "this one" - so the camera dollies in until that unit alone fills the
 * clear part of the window, and the reveal that was following the pointer
 * is PINNED to it. Nothing else changes: it is the same drawing, the same
 * straight-down roll and the same furniture arriving out of the floor,
 * only closer and held. The page swaps the four type cards for that flat's
 * own card beside it, which is the whole point of going in.
 *
 * It is a pure dolly. The camera and its target come down the same
 * vertical the floor view was already on, so nothing rotates and the plan
 * never leaves the frame on the way - a visitor can follow their own flat
 * all the way in.
 * -------------------------------------------------------------------- */
let planFocus = - 1;             // which unit is open, or -1 for the storey
let planFocusSaid = - 2;         // ...and what the page was last told

/* The air left round the open flat. Under 1 on purpose: what the fit
 * measures is the unit's whole BOX, floor to ceiling, and at this tilt the
 * top corners of its back wall are the highest thing in it - a strip of
 * wall head with nothing on it. Holding that inside the band kept the
 * rooms a size smaller than the window could carry. */
const FOCUS_FIT = 0.97;
const FOCUS_MIN = 9;             // ...and how close the camera may ever get
const FOCUS_HEAD = 66;           // the page's own header, kept off the flat
const FOCUS_FOOT = 26;           // ...and the sill it stands on
const FOCUS_DUR = 1250;
/* How far OFF THE VERTICAL the open flat is seen from, in degrees. The
 * floor view looks straight down; this is the only thing the third step
 * changes about the shot.
 *
 * It is a pitch and nothing else. The camera swings down from over the
 * flat about the FRAME's own right - the same axis the picture's left and
 * right already lie on - so the roll and the heading it had looking
 * straight down are exactly the roll and the heading it keeps: the row
 * still runs across the window, the depth still runs up it, and nothing
 * turns under the visitor on the way in. Only the angle changes. */
const FOCUS_TILT = 32;
const FOCUS_PASSES = 5;

/* A unit's own rectangle in the row's plan coordinates: the bay it stands
 * in across the block, and the half of the depth it is in. Read off the
 * same bay table the shader picks units with, so the two cannot disagree
 * about where a flat ends. */
function planUnitBox( unit ) {
	const f = meta && meta.flat, b = meta && meta.block && meta.block.floors;
	if ( ! f || ! f.row || unit < 0 ) return null;
	const col = unit & 3, back = unit >= 4;
	const s = f.row.starts, end = f.row.end, depth = ( b && b.depth ) || 18;
	return {
		x0: s[ col ], x1: col < 3 ? s[ col + 1 ] : end,
		y0: back ? depth * 0.5 : 0, y1: back ? depth : depth * 0.5,
	};
}

/* One flat, seen from the show flat's own angle and stood in the window
 * the page has left clear.
 *
 * NOT straight down. Straight down is how a STOREY is read - eight plans
 * laid side by side, which is the whole point of the view behind this one
 * - but one flat seen straight down is still a plan, and the third step is
 * where a visitor should stop reading and start looking at rooms. So the
 * camera comes off the vertical onto the angle the sales render uses.
 *
 * It comes over the unit's OWN outer wall - the street for a flat on the
 * street line, the courtyard for one behind it - so there is never another
 * flat standing between the camera and the rooms. That is the only thing
 * the front and back halves of the row do differently.
 *
 * ACROSS the frame it is fitted to the clear band rather than to the
 * window: the storey's own shot only slides clear of the cards, because a
 * whole row fitted into the narrower band is a plan nobody can read, but
 * one flat fits it easily and belongs in the middle of the glass that is
 * actually showing. Down the frame it answers to the page's header rather
 * than to the line the cards start on - there is nothing beside it to line
 * up with, and holding it under that line threw away a third of the height
 * it could have had. */
/* `LV` = { box, F, head } frames a box of the real building's plate - one
 * flat's polygon and its loggias - with everything below unchanged. */
function planFocusPose( unit, LV = null ) {
	const box = LV ? LV.box : planUnitBox( unit );
	if ( ! box ) return planPose();
	const F = LV ? LV.F : planFrame();
	const { ex, ey, o, up, fov, tan, ar, fw } = F;
	const fh = frameEl.clientHeight || 1;
	const b = meta && meta.block && meta.block.floors;
	const head = LV ? LV.head : ( ( b && b.h ) || 3 ) - 0.2;     // the storey's own clear height

	/* The unit as a BOX, floor to ceiling - eight corners, not four. Seen
	 * from an angle a rectangle draws as a hexagon and its footprint says
	 * nothing about how much of the frame it takes; the walls standing up
	 * out of it are most of what has to fit. */
	const corners = [];
	for ( const x of [ box.x0, box.x1 ] )
		for ( const y of [ box.y0, box.y1 ] )
			for ( const z of [ 0, head ] )
				corners.push( o.clone().addScaledVector( ex, x )
					.addScaledVector( ey, y ).setY( o.y + z ) );

	const t0 = o.clone()
		.addScaledVector( ex, ( box.x0 + box.x1 ) * 0.5 )
		.addScaledVector( ey, ( box.y0 + box.y1 ) * 0.5 );
	t0.y = o.y + head * 0.4;

	/* The camera's own stand-off, as a direction out of the flat: straight
	 * up, swung back by `FOCUS_TILT` about the frame's right.
	 *
	 * ALWAYS THE SAME WAY, for every flat on the storey. It swung out over
	 * whichever side of the block the unit stood on first - the street for
	 * the street line, the courtyard for the row behind it - which keeps
	 * every flat clear of its neighbour's walls and is wrong anyway: the
	 * two rows then came out facing opposite ways, and the back line read
	 * as the plan turned upside down. A visitor stepping along a storey is
	 * looking at one building from one place, and every flat in it has to
	 * be the same way up.
	 *
	 * So the lean is the street's, always - the side the facade and the
	 * balconies are on, and the side the show flat's own shot looks from.
	 * The back line pays a wall's worth of its near edge for it, about a
	 * metre and a half, which is the corridor side of the plan. */
	/* ...and the real building's plan frame runs the other way: its +y is
	 * TOWARDS the street (CONTRACT.md "Frames"), where the old block's ey
	 * ran away from it - so the same street lean is the opposite sign. Got
	 * wrong, the camera sat over the courtyard looking back into the sun
	 * and every sunlit parquet floor came out as a blown highlight. */
	const lean = ( LV ? 1 : - 1 ) * Math.sign( ey.dot( up ) ) || - 1;
	const th = FOCUS_TILT * Math.PI / 180;
	const dir = new THREE.Vector3( 0, Math.cos( th ), 0 )
		.addScaledVector( up, Math.sin( th ) * lean ).normalize();

	const inset = Math.max( 0, Math.min( uiInset, fw * 0.55 ) );
	const sill = uiTop > 0 ? uiTop + PLAN_SILL : 0;
	/* On the narrow layout the panel lies ACROSS the top of the plate
	 * rather than beside it, and there the cards' line is still the floor
	 * or the flat would open underneath them. */
	const top = inset > 0 ? FOCUS_HEAD : Math.max( sill, FOCUS_HEAD );
	/* Floors under both, so a window squeezed to a sliver - or a page that
	 * has grown its panel over most of it - flies the camera away for ever
	 * instead of framing anything. */
	const foot = Math.max( FOCUS_FOOT, uiFoot );
	const clearW = Math.max( fw * 0.34, fw - inset );
	const clearH = Math.max( fh * 0.28, fh - top - foot );
	const bandX = inset + clearW * 0.5, bandY = top + clearH * 0.5;

	/* Fitted by MEASURING rather than by arithmetic: the pose is built, the
	 * eight corners are projected through it and the stand-off is scaled by
	 * how far outside the band they land - five times over. There is no
	 * closed form for an oblique box fitted to a band that is not the
	 * window, and the passes land inside a pixel long before the fifth. */
	const tmp = new THREE.PerspectiveCamera( fov, ar, 0.1, 4000 );
	const off = new THREE.Vector3(), t = new THREE.Vector3(), p = new THREE.Vector3();
	const q = new THREE.Vector3(), right = new THREE.Vector3();
	const cup = new THREE.Vector3(), fwd = new THREE.Vector3();
	let d = 26;
	for ( let pass = 0; pass < FOCUS_PASSES; pass ++ ) {
		t.copy( t0 ).add( off );
		p.copy( t ).addScaledVector( dir, d );
		tmp.position.copy( p );
		tmp.up.copy( up );
		tmp.lookAt( t );
		tmp.aspect = ar;
		tmp.updateMatrixWorld();
		tmp.updateProjectionMatrix();
		let x0 = Infinity, x1 = - Infinity, y0 = Infinity, y1 = - Infinity;
		for ( const c of corners ) {
			q.copy( c ).project( tmp );
			const px = ( q.x * 0.5 + 0.5 ) * fw, py = ( - q.y * 0.5 + 0.5 ) * fh;
			x0 = Math.min( x0, px ); x1 = Math.max( x1, px );
			y0 = Math.min( y0, py ); y1 = Math.max( y1, py );
		}
		d = Math.max( FOCUS_MIN, d * FOCUS_FIT
			* Math.max( ( x1 - x0 ) / clearW, ( y1 - y0 ) / clearH ) );
		/* ...and the box stood in the middle of the band, which is the
		 * camera and its target sliding together square to the view - so
		 * the picture translates and the angle it is seen from does not
		 * change at all. */
		const perPx = 2 * ( d * tan * ar ) / fw;
		tmp.matrixWorld.extractBasis( right, cup, fwd );
		off.addScaledVector( right, - ( bandX - ( x0 + x1 ) * 0.5 ) * perPx )
			.addScaledVector( cup, ( bandY - ( y0 + y1 ) * 0.5 ) * perPx );
	}
	t.copy( t0 ).add( off );
	p.copy( t ).addScaledVector( dir, d );
	tmp.position.copy( p );
	tmp.up.copy( up );
	tmp.lookAt( t );
	/* `up` is the floor view's own - `planUp`, caught off the street
	 * heading - and it is what holds the roll still through the tilt.
	 * Taking +Y here instead would re-roll the picture the moment the
	 * camera came off the vertical, which is the turn this shot must not
	 * have. */
	return { p: p.clone(), q: tmp.quaternion.clone(), fov, shift: 0,
		target: t.clone(), up: up.clone() };
}

/* The dolly itself. Not `flyCamera`: that one cranes over a control point
 * high above the path, which is what carries the shot over the roof on the
 * way in from the street and is exactly wrong here - both ends of this
 * move are already straight down over the same storey, and a lift would
 * rise away from the flat before dropping back onto it. */
function planFocusFly( to ) {
	const p0 = camera.position.clone(), q0 = camera.quaternion.clone();
	const fov0 = camera.fov, shift0 = camera.lensShift;
	planKillTween();
	tween( FOCUS_DUR, 0, ( t ) => {
		const e = easeInOut( t );
		camera.position.lerpVectors( p0, to.p, e );
		camera.quaternion.slerpQuaternions( q0, to.q, e );
		camera.fov = fov0 + ( to.fov - fov0 ) * e;
		camera.lensShift = shift0 + ( to.shift - shift0 ) * e;
		camera.updateProjectionMatrix();
	}, () => {
		planTween = null;
		setMode( 'hero' );           // lands it exactly, through `planShot`
	} );
	planTween = tweens[ tweens.length - 1 ];
}

/* Open a flat, or - with -1 - close it and go back to the storey.
 *
 * The page is told BEFORE the pose is built, the way `lp:scene` is, because
 * what it does about it changes the framing: swapping the four type cards
 * for one flat's card is a different width and a different top line, and
 * the shot has to fly to where the window will be rather than to where it
 * was. `sceneSettling` is what stops the `setInset` that comes straight
 * back from re-shooting the camera onto the destination mid-announce. */
function planFocusSet( unit, animate = true ) {
	if ( ! planDragOwns() ) return;
	const u = ( unit >= 0 && unit < 8 && planUnitBox( unit ) ) ? unit | 0 : - 1;
	if ( u === planFocus ) return;
	planKillTween();
	planDrag = null;
	planVel = 0;
	/* Closing a flat - or opening a different one - takes the visitor out
	 * of whatever room they were standing in, and the shell it was built
	 * for with them. The pose below is the open flat's, so there is
	 * nothing to fly: the room is simply not where this is going. */
	roomFocus = - 1;
	roomSaid = - 2;
	roomShellClear();
	planFocus = u;
	/* ...and the PAGE has to be told, which is the one thing this used to
	 * leave out. Every other way out of a room goes through `setScene`,
	 * which tells it on the way past; clicking a neighbouring flat does
	 * not, so the room bar and its buttons sat over the open flat with
	 * `roomview` still on the body - the way back out of a room nobody
	 * was in any more. */
	roomTell();
	/* The hover is pinned while a flat is open. The pointer leaves the plan
	 * the moment the card beside it is there to be read, and the rooms
	 * draining back to a drawing behind the visitor's own eyes is the one
	 * thing this step must not do. */
	if ( u >= 0 ) planHot = u;
	// ...and let go of again on the way out, so the storey does not keep one
	// flat furnished under nobody's pointer. The hover re-tests on the next
	// frame and lights it again if the pointer really is still on it.
	else { planHot = - 1; floorDirty = true; }
	planFocusTell();
	announcePlan();
	const pose = u >= 0 ? planFocusPose( u ) : planPose( planPanM );
	if ( animate ) planFocusFly( pose );
	else { applyPose( pose ); setMode( 'hero' ); }
	shadowDirty();
	invalidate();
}

function planFocusTell( force = false ) {
	const u = ( sceneNo === 2 && scene2View === 'plan' ) ? planFocus : - 1;
	if ( ! force && u === planFocusSaid ) return;
	planFocusSaid = u;
	/* Saved and put back rather than cleared: `setScene` announces through
	 * here too and owns the flag for the whole of its own call. */
	const was = sceneSettling;
	sceneSettling = true;
	try {
		announce( 'planfocus', { unit: u, floor: sceneFloor,
			front: u >= 0 ? u < 4 : null, col: u >= 0 ? ( u & 3 ) : - 1 } );
	} finally { sceneSettling = was; }
}

/* ==================================================== inside the rooms
 * The fourth step, and the last one. A visitor who has chosen a flat is
 * standing over it reading a plan, and what they are really asking is what
 * it is like to BE in it. So every room in the open flat carries a dot,
 * the dot names its room under the pointer, and clicking it puts the
 * camera inside that room at eye height, where it can be turned on the
 * spot - and walked, since the page's fly controls are already live.
 *
 * Three things make it work, and two of them are not in the model:
 *
 *   THE STANCES are placed by hand. "The best view of a room" is a
 *   composition - the bed from its foot with the window behind it, the
 *   kitchen looked down its own run - and no centroid finds one. They are
 *   written below in the flat's own metres, the ones `lib_flat.py` builds
 *   it in, and checked against shots of each room.
 *
 *   THE SHELL. The show flat is a CUTAWAY: its partitions stop at 1.45 m
 *   and it has no ceiling at all, because that is what lets the storey be
 *   read from above. Stand inside it and the trick is over - you look over
 *   every wall into the next room and up into the sky. So the room view
 *   builds the missing top of the flat in the browser: the partitions
 *   carried from the cut up to the head of the outer shell, a ceiling over
 *   them, and the four doors - which the cut beheads - given back their
 *   lining, architrave, leaf and top hinge. Forty-odd boxes, built when a
 *   flat is opened and thrown away when it closes, in the same materials
 *   the flat is already drawn in. It never stands in the plan: a ceiling
 *   over a flat seen from above is a lid on it, so it is switched on as
 *   the dive passes down through its own ceiling, where it is edge on and
 *   nobody sees it arrive.
 *
 *   THE DOTS are DOM, like the area badges and for the same reason: they
 *   have to be read and hit at whatever scale the plate is at, and a
 *   sprite in the scene would be ground through the temporal filter and
 *   the grade with everything else. The scene projects them and names
 *   them; the page draws them, hovers them and sends the click back.
 * -------------------------------------------------------------------- */

/* The flat's own plan, in the metres `blender/lib_flat.py` builds it in.
 * Every number is an inside face and has a twin up there. They are copied
 * rather than measured off the model because the model arrives WELDED -
 * one mesh per material for a whole row of flats - and there is nothing
 * left in it that knows where a bathroom ends. `scene_meta.json` carries
 * the frame they are read in, which is the one thing that does move. */
/* The flat's plan in its own metres, which the room shell is rebuilt from.
 *
 * These are only the FALLBACK. The build writes the same table into
 * `scene_meta.json` (`flat.plan`) and `adoptPlan` copies it over this one
 * the moment the meta lands, because a hand copy drifts: `Y_ENT` moved from
 * 8.20 to 8.80 when the two lines of flats were brought together at the
 * middle of the block and this table did not follow. The shell then built
 * the entrance wall 0.60 m thick with the front door's leaf 0.30 m out of
 * its own opening - a door and a wall that broke in half at the cut line,
 * and only from inside a room, which is the only place the shell is on. */
const FM = {
	X_GABLE: 0.46, X_PARTY: 11.34,          // the two ends, inside faces
	Y_FAC: 0.35, Y_LOG: 2.07,               // facade, loggia back wall
	Y_ENT: 8.80, YC: 9.00,                  // entrance wall, both faces
	X_LIV: 5.32, X_BED: 8.40, X_BATH: 9.18, Y_P23: 5.30,    // the partitions
	PT: 0.12,                               // ...and how thick they are
	LOG_LIV: 0.85, LOG_BED: 9.17, LOG_OP: 1.76, LOG_RET: 0.185,
	SEAM: 5.20,                             // where units 1-3 lose their 0.30
	FZ: 0.02,                               // the parquet, over the slab
	FZT: 0.025,                             // ...and the tiling, on the balconies
	CUT: 1.47,                              // ...and where the cutaway stops
	TOP: 2.45,                              // the outer shell's head: the ceiling
	DOOR_H: 2.05, LT: 0.018, AW: 0.072, AP: 0.016,   // door head, lining, architrave
};
/* Only keys this table already carries, so a stray one in the file cannot
 * invent a dimension the shell never asked for. */
function adoptPlan( m ) {
	const p = m && m.flat && m.flat.plan;
	if ( ! p ) return;
	for ( const k of Object.keys( FM ) )
		if ( typeof p[ k ] === 'number' ) FM[ k ] = p[ k ];
}

/* Where a visitor stands in each room, and what they are looking at.
 *
 * `dot` is where the room is named on the plan, `eye` where the camera
 * stands and `at` what it is aimed at - all in the flat's own metres, with
 * the two heights measured off the floor. The field is VERTICAL and 52
 * degrees is about a 20 mm lens on a full frame: wide, the way an interior
 * is always shot, but not the fish-eye that 64 and up turns into on a
 * window this shape.
 *
 * Every stance stands in a corner and looks diagonally across its room.
 * That is not a style: these rooms are 3 m across and a camera in the
 * middle of one sees a wall. */
const ROOMS = [
	{ key: 'living', name: 'Living room', dot: [ 3.30, 3.30 ],
		eye: [ 4.70, 6.55 ], h: 1.60, at: [ 1.20, 2.40, 1.15 ], fov: 52 },
	{ key: 'kitchen', name: 'Kitchen & dining', dot: [ 1.95, 6.90 ],
		eye: [ 4.35, 3.70 ], h: 1.60, at: [ 1.15, 7.30, 1.05 ], fov: 52 },
	{ key: 'master', name: 'Master bedroom', dot: [ 6.90, 2.70 ],
		eye: [ 6.80, 4.52 ], h: 1.60, at: [ 6.55, 0.60, 1.20 ], fov: 52 },
	{ key: 'bed2', name: 'Bedroom 2', dot: [ 9.95, 3.40 ],
		eye: [ 8.95, 5.00 ], h: 1.60, at: [ 10.60, 1.70, 1.15 ], fov: 52 },
	{ key: 'bath', name: 'Bathroom', dot: [ 10.35, 6.80 ],
		eye: [ 9.48, 5.72 ], h: 1.60, at: [ 11.15, 8.05, 0.95 ], fov: 58 },
	/* Down the hall and straight through the cased opening into the living
	 * room, rather than across the hall at a wall: a corridor's own four
	 * square metres are not what anybody is buying, and the one thing it
	 * can show is how far the flat runs. */
	{ key: 'hall', name: 'Hall', dot: [ 7.25, 6.95 ],
		eye: [ 8.55, 6.95 ], h: 1.60, at: [ 5.00, 7.30, 1.30 ], fov: 56 },
	{ key: 'balc_liv', name: 'Living balcony', dot: [ 1.73, 1.20 ],
		eye: [ 1.73, 1.52 ], h: 1.60, at: [ 1.90, - 26.0, - 3.4 ], fov: 52 },
	{ key: 'balc_bed', name: 'Bedroom balcony', dot: [ 10.05, 1.20 ],
		eye: [ 10.05, 1.52 ], h: 1.60, at: [ 9.88, - 26.0, - 3.4 ], fov: 52 },
];

/* The four doors, as `lib_flat.build_flat` hangs them - one row each,
 * read by the three things that need to know where a door is: the shell
 * that carries its frame up past the cut, the rig that swings its leaf,
 * and the body that cannot walk through it while it is shut.
 *
 * `pos` and `w` are the structural opening along the wall and `t0`/`t1`
 * its two faces, so `along` says which of those is x. The leaf hangs on
 * the `lo` or `hi` jamb and is MODELLED `angle` degrees open: that is the
 * pose the dollhouse and the floor view are shot in, and the pose the
 * swing comes to rest at. `key` is the build's own item name less its
 * `door_` - `flat_door_master_swing__*` is the master's swinging half.
 * `shut` is the dark panel across the back of an opening that has one.
 *
 * Built on CALL and not held in a constant, because every face in it is
 * read off `FM` and `FM` is rewritten from the build's own plan the moment
 * the meta lands. A table made at load would have frozen `Y_ENT` at the
 * 8.20 the literals carry rather than the 8.80 the build measures - which
 * is the stale entrance wall, with the front door's leaf 0.30 m out of its
 * own opening, put straight back. Four small objects, made when a flat is
 * opened and not on any frame. */
const doorRows = () => [
	{ key: 'entrance', pos: 7.40, w: 0.92, t0: FM.Y_ENT, t1: FM.YC,
		along: 'x', hinge: 'lo', angle: 68, side: - 1,
		shut: [ FM.YC - 0.03, FM.YC ] },
	{ key: 'master', pos: 6.30, w: 0.80, t0: FM.Y_P23, t1: FM.Y_P23 + FM.PT,
		along: 'x', hinge: 'hi', angle: 70, side: - 1 },
	{ key: 'bed2', pos: 9.30, w: 0.80, t0: FM.Y_P23, t1: FM.Y_P23 + FM.PT,
		along: 'x', hinge: 'lo', angle: 75, side: - 1 },
	{ key: 'bath', pos: 6.35, w: 0.80, t0: FM.X_BATH, t1: FM.X_BATH + FM.PT,
		along: 'y', hinge: 'lo', angle: 84, side: - 1 },
];

/* A door's leaf, `deg` degrees open, as a heading in the flat's own plan -
 * the one piece of arithmetic the rig, the collider and the shell all have
 * to agree on, so there is one copy of it. `lib_flat.door` lays the leaf
 * along `u = (sgn cos a, side sin a)` in the wall's own (s, t) frame, with
 * s running along the wall; this is that vector in plan x and y, mirrored
 * for the back line the way every other heading in the flat is. */
function doorHeading( D, back, deg ) {
	const a = deg * Math.PI / 180;
	const us = ( D.hinge === 'lo' ? 1 : - 1 ) * Math.cos( a );
	const ut = D.side * Math.sin( a );
	const d = D.along === 'x' ? [ us, ut ] : [ ut, us ];
	const th = Math.atan2( d[ 1 ], d[ 0 ] );
	return back ? - th : th;
}

/* Where its hinge stands, and the middle of its opening, both in the
 * flat's own plan. The hinge is on the jamb the leaf hangs from and the
 * middle of the opening is what a body walks at. */
const doorHinge = ( D ) => D.along === 'x'
	? [ D.hinge === 'lo' ? D.pos : D.pos + D.w, ( D.t0 + D.t1 ) * 0.5 ]
	: [ ( D.t0 + D.t1 ) * 0.5, D.hinge === 'lo' ? D.pos : D.pos + D.w ];
const doorMiddle = ( D ) => D.along === 'x'
	? [ D.pos + D.w * 0.5, ( D.t0 + D.t1 ) * 0.5 ]
	: [ ( D.t0 + D.t1 ) * 0.5, D.pos + D.w * 0.5 ];

/* A point in the flat's own plan, in the world, for whichever of the eight
 * units is open.
 *
 * Units 1-3 are not copies of unit 0 but WARPED copies: unit 0 was fitted
 * 11.84 m wide because its first window bay is 0.30 wider than the rest,
 * and `build_row` takes that 0.30 out at the seam between the two windows.
 * So everything east of the seam stands 0.30 further west than the unit's
 * own start would put it. The back line is the whole flat MIRRORED at the
 * middle of the block, not turned round - see `build_back_row` - so its y
 * is the depth less ours and anything with a heading has its heading
 * negated. One map, applied to every point and every box below. */
function roomMap( unit ) {
	const f = meta && meta.flat, b = meta && meta.block && meta.block.floors;
	const s = ( f && f.row && f.row.starts ) || [ 0, 0, 0, 0 ];
	const col = unit & 3, back = unit >= 4;
	const dx = col > 0 ? s[ col ] - s[ 0 ] : 0;
	// unit 0's own width less a copy's, read off the bay table rather than
	// written down: the bays are fitted upstream and this moves with them
	const shrink = col > 0 ? ( s[ 1 ] - s[ 0 ] ) - ( s[ 2 ] - s[ 1 ] ) : 0;
	const depth = ( b && b.depth ) || 18;
	return {
		back,
		x: ( lx ) => lx + dx - ( lx > FM.SEAM ? shrink : 0 ),
		y: ( ly ) => back ? depth - ly : ly,
	};
}

/* ...and the same point as somewhere the camera can stand: on the storey
 * the scene is open on, which is the only thing between the flat's own
 * frame and the world. */
function roomWorld( unit, lx, ly, h ) {
	const { ex, ey } = flatFrame();
	const f = meta && meta.flat;
	const o = new THREE.Vector3( ...( f ? f.origin : [ 0, 32, 0 ] ) );
	const m = roomMap( unit );
	return o.clone().addScaledVector( ex, m.x( lx ) ).addScaledVector( ey, m.y( ly ) )
		.setY( o.y + h + floorDrop() );
}

/* ------------------------------------------------------- the shell
 * The top of the flat, which the cutaway took away. Built in the flat's
 * own metres and laid into the world with the frame's own basis, so it
 * lands on the walls it is continuing rather than near them.
 *
 * It is built in the SAME materials as the flat, not in copies, which is
 * what keeps it inside the floor view's drawing: those materials already
 * turn to ink for a flat nobody is pointing at and back to plaster for the
 * one that is open, and the shell is carried along with them for free. */
let roomShell = null, roomShellUnit = - 2, roomShellOn = false;

function roomShellMats() {
	const want = { wall: 'int_wall', gloss: 'int_white_gloss', leaf: 'int_door_leaf',
		tile: 'int_tile_wall', stone: 'int_stone_dark' };
	const out = {};
	if ( ! groups.flat ) return out;
	groups.flat.traverse( ( o ) => {
		if ( ! o.isMesh || Array.isArray( o.material ) ) return;
		const n = o.material.name;
		for ( const k of Object.keys( want ) )
			if ( ! out[ k ] && n === want[ k ] ) out[ k ] = o.material;
	} );
	return out;
}

/* Every box the shell is made of, in one pass, keyed by material. The
 * geometry is built in a frame of the flat's own - x along it, y up, z
 * ACROSS it the other way round - because (ex, up, ey) is left handed and
 * a basis with a negative determinant turns every face it builds inside
 * out. With -ey the determinant is +1 and a box is a box. */
function roomShellGeo( unit ) {
	const m = roomMap( unit );
	const F = FM, by = new Map();
	const put = ( k, g ) => { if ( ! by.has( k ) ) by.set( k, [] ); by.get( k ).push( g ); };

	/* A piece CONTINUING one the cutaway beheaded sinks into it rather
	 * than standing on it. Two faces in the same plane is the one thing
	 * that cannot be left here: the top of a cut wall faces the sky and is
	 * bright, the underside of the piece over it faces the floor and is
	 * dark, and the depth buffer picks between them a pixel at a time - a
	 * hard bright line round every room at 1.47 m, which is exactly the
	 * seam the shell is there to hide. So a gripping piece reaches 40 mm
	 * DOWN into the wall under it, which buries its own underside, and is
	 * held 1 mm inside that wall's faces so its sides do not fight them
	 * either. A millimetre is a third of a pixel at arm's length. */
	const GRIP = 0.040, SHY = 0.001;
	const box = ( k, x0, y0, z0, x1, y1, z1, grip ) => {
		let ax0 = m.x( x0 ), ax1 = m.x( x1 ), ay0 = m.y( y0 ), ay1 = m.y( y1 );
		if ( ax0 > ax1 ) { const t = ax0; ax0 = ax1; ax1 = t; }
		if ( ay0 > ay1 ) { const t = ay0; ay0 = ay1; ay1 = t; }
		if ( grip ) { ax0 += SHY; ax1 -= SHY; ay0 += SHY; ay1 -= SHY; z0 -= GRIP; }
		const w = ax1 - ax0, d = ay1 - ay0, h = z1 - z0;
		if ( w < 1e-4 || d < 1e-4 || h < 1e-4 ) return;
		const g = new THREE.BoxGeometry( w, h, d );
		g.translate( ( ax0 + ax1 ) * 0.5, ( z0 + z1 ) * 0.5, - ( ay0 + ay1 ) * 0.5 );
		put( k, g );
	};
	const pin = ( k, cx, cy, z0, z1, r ) => {
		if ( z1 - z0 < 1e-4 ) return;
		const g = new THREE.CylinderGeometry( r, r, z1 - z0, 10 );
		g.translate( m.x( cx ), ( z0 + z1 ) * 0.5, - m.y( cy ) );
		put( k, g );
	};

	const ZC = F.CUT, ZT = F.TOP;
	/* Where the wall starts again over a door: the top of its LINING, not
	 * the top of its architrave. The architrave is nailed to the FACE of
	 * the wall and stands 16 mm proud of it - it was never in the hole -
	 * so a lintel that cleared it would leave a 72 mm slot straight
	 * through the wall over every door in the flat. Six millimetres under
	 * it, so the lintel grips the lining head instead of landing on it. */
	const AT = F.FZ + F.DOOR_H + F.LT - 0.006;

	/* A beheaded wall, carried back up to the ceiling with its openings
	 * left out of it. `gaps` are [ from, to, head ]: `head` is where the
	 * lintel over that opening begins, or the ceiling itself for an
	 * opening that was never a door and has no head at all. */
	const capX = ( y0, y1, x0, x1, gaps ) => {
		let at = x0;
		for ( const [ a, b, head ] of gaps ) {
			box( 'wall', at, y0, ZC, a, y1, ZT, true );
			box( 'wall', a, y0, head, b, y1, ZT, head < ZT );
			at = b;
		}
		box( 'wall', at, y0, ZC, x1, y1, ZT, true );
	};
	const capY = ( x0, x1, y0, y1, gaps ) => {
		let at = y0;
		for ( const [ a, b, head ] of gaps ) {
			box( 'wall', x0, at, ZC, x1, a, ZT, true );
			box( 'wall', x0, a, head, x1, b, ZT, head < ZT );
			at = b;
		}
		box( 'wall', x0, at, ZC, x1, y1, ZT, true );
	};

	// the entrance wall, and the three partitions that carry doors
	capX( F.Y_ENT, F.YC, F.X_GABLE, F.X_PARTY, [ [ 7.40, 8.30, AT ] ] );
	capX( F.Y_P23, F.Y_P23 + F.PT, F.X_LIV + F.PT, F.X_PARTY,
		[ [ 6.30, 7.10, AT ], [ 9.30, 10.10, AT ] ] );
	capY( F.X_BATH, F.X_BATH + F.PT, F.Y_P23 + F.PT, F.Y_ENT, [ [ 6.35, 7.15, AT ] ] );
	// ...the living room's, whose opening on to the hall is cased and runs
	// to the ceiling, so there is no lintel over it to build
	capY( F.X_LIV, F.X_LIV + F.PT, F.Y_FAC, F.Y_ENT, [ [ 6.30, F.Y_ENT, ZT ] ] );
	capY( F.X_BED, F.X_BED + F.PT, F.Y_FAC, F.Y_P23, [] );

	/* The ceiling, at the head of the outer shell so the two meet with no
	 * slot of sky between them - over the rooms only. The loggias are
	 * outside it, and on the top floor they have no soffit at all: a
	 * balcony with a lid on it would be a balcony nobody can see out of. */
	const CT = 0.05, CB = 0.03, E = 0.03;
	const l0 = F.LOG_LIV - F.LOG_RET, l1 = F.LOG_LIV + F.LOG_OP + F.LOG_RET;
	const b0 = F.LOG_BED - F.LOG_RET, b1 = F.LOG_BED + F.LOG_OP + F.LOG_RET;
	/* Its soffit is 30 mm UNDER the head of the outer shell and every edge
	 * runs 30 mm INTO the wall it dies against, for the same reason the
	 * caps grip: a ceiling laid exactly on the tops of the walls is six
	 * metres of two faces in one plane, and the wall tops would flicker
	 * through it the whole way round the room. Buried, the junction is a
	 * line and not a seam. */
	box( 'wall', F.X_GABLE - E, F.Y_LOG - E, ZT - CB, F.X_PARTY + E, F.YC + E, ZT + CT );
	box( 'wall', F.X_GABLE - E, F.Y_FAC - E, ZT - CB, l0 + E, F.Y_LOG - E, ZT + CT );
	box( 'wall', l1 - E, F.Y_FAC - E, ZT - CB, b0 + E, F.Y_LOG - E, ZT + CT );
	box( 'wall', b1 - E, F.Y_FAC - E, ZT - CB, F.X_PARTY + E, F.Y_LOG - E, ZT + CT );

	/* The bathroom is tiled to the cut and no further, so carrying its
	 * walls up bare would leave a band of plaster over the tiles with the
	 * joint at exactly the height the cutaway happens to be. The tiling
	 * goes up with them, to the 2.10 m a bathroom is actually tiled to -
	 * these are `build_flat`'s own five faces, with its door left out. */
	const bx0 = F.X_BATH + F.PT, bx1 = F.X_PARTY;
	const by0 = F.Y_P23 + F.PT, by1 = F.Y_ENT;
	const TH = 0.015, TZ = F.FZ + 2.10;
	box( 'tile', bx0, by0, ZC, bx0 + TH, 6.35, TZ, true );
	box( 'tile', bx0, 7.15, ZC, bx0 + TH, by1, TZ, true );
	box( 'tile', bx1 - TH, by0, ZC, bx1, by1, TZ, true );
	box( 'tile', bx0, by0, ZC, bx1, by0 + TH, TZ, true );
	box( 'tile', bx0, by1 - TH, ZC, bx1, by1, TZ, true );

	/* The top of a door. `lib_flat.door()` builds a 2.05 m door and then
	 * stops the whole thing at the cut, so what is missing is the same
	 * door above 1.47: the lining through the reveal and its head, the
	 * mitred architrave on both faces, the leaf, its lipping, and the top
	 * butt hinge. The numbers are that function's own. */
	const doorTop = ( D ) => {
		const { pos, w, t0, t1, along, shut } = D;
		const z0 = F.FZ, H = F.DOOR_H, LT = F.LT, AW = F.AW, AP = F.AP;
		// s runs along the wall, t across it - the door's own frame
		const xy = along === 'x' ? ( s, t ) => [ s, t ] : ( s, t ) => [ t, s ];
		/* ...and only the pieces the cut actually went through grip. A
		 * lining head or an architrave head begins above 1.47 and has
		 * nothing underneath it to sink into. */
		const sbox = ( k, s0, ta, zb, s1, tb, zt ) => {
			const grip = zb < ZC;
			const zb_ = Math.max( zb, ZC );
			if ( zt - zb_ < 1e-4 ) return;
			const a = xy( s0, ta ), b = xy( s1, tb );
			box( k, Math.min( a[ 0 ], b[ 0 ] ), Math.min( a[ 1 ], b[ 1 ] ), zb_,
				Math.max( a[ 0 ], b[ 0 ] ), Math.max( a[ 1 ], b[ 1 ] ), zt, grip );
		};
		sbox( 'gloss', pos - LT, t0 - 0.002, z0, pos, t1 + 0.002, z0 + H );
		sbox( 'gloss', pos + w, t0 - 0.002, z0, pos + w + LT, t1 + 0.002, z0 + H );
		sbox( 'gloss', pos - LT, t0 - 0.002, z0 + H, pos + w + LT, t1 + 0.002, z0 + H + LT );
		for ( const [ ta, tb ] of [ [ t0 - AP, t0 ], [ t1, t1 + AP ] ] ) {
			sbox( 'gloss', pos - LT - AW, ta, z0, pos - LT, tb, z0 + H + LT + AW );
			sbox( 'gloss', pos + w + LT, ta, z0, pos + w + LT + AW, tb, z0 + H + LT + AW );
			sbox( 'gloss', pos - LT - AW, ta, z0 + H + LT, pos + w + LT + AW, tb, z0 + H + LT + AW );
		}
		/* The top butt hinge, which stands ON the hinge axis and so is the
		 * one piece of a door the swing does not move. `lib_flat` caps it
		 * with everything else at the cut, and 1.81 m is above that. */
		const hp = doorHinge( D ), hz = z0 + H - 0.24;
		pin( 'gloss', hp[ 0 ], hp[ 1 ], Math.max( ZC, hz - 0.048 ), hz + 0.048, 0.013 );
		/* The LEAF above the cut is not here: it belongs to `doorRig`,
		 * which hangs the model's own half of it on a pivot and has to
		 * carry this half round with it. Built here it would stand at the
		 * modelled angle while the door below it swung. */
		/* ...and the blind at the back of the opening, where there is one.
		 * The two lines of flats meet in the entrance wall, so `lib_flat`
		 * closes the back of that doorway with a dark panel - otherwise you
		 * look through two front doors into the flat behind. The panel is
		 * cut at 1.47 with everything else, and without it carried up here
		 * the top half of the doorway is a hole straight out over the
		 * storey: the wall and the door both read as broken off. */
		if ( shut ) sbox( 'stone', pos, shut[ 0 ], z0, pos + w, shut[ 1 ], z0 + H );
	};
	doorRows().forEach( doorTop );
	return by;
}

/* The shell, the doors on their hinges and the floor plan under the feet
 * all live exactly as long as one open flat, and every path that closes a
 * flat already comes through here. */
function roomShellClear() {
	cityInside( false );              // ...and the street is given back
	roomShadow( false );
	walkOff();
	walkGridSet( - 1 );
	doorRigClear();
	if ( ! roomShell ) return;
	roomShell.traverse( ( o ) => { if ( o.isMesh ) o.geometry.dispose(); } );
	roomShell.removeFromParent();
	roomShell = null;
	roomShellUnit = - 2;
	roomShellOn = false;
}

/* The flat's own frame as a matrix, for anything built in the plan's
 * metres and laid into the model beside the pieces it continues.
 *
 * x runs along the flat, y up and z ACROSS it THE OTHER WAY ROUND, because
 * (ex, up, ey) is left handed and a basis with a negative determinant
 * turns every face it builds inside out. With -ey the determinant is +1
 * and a box is a box - hence the sign on every y that goes through it.
 *
 * It carries no storey drop: the flat's meshes arrive welded into world
 * space at the top floor and `groups.flat` holds the drop for all of them,
 * so anything built here hangs in that group and goes down with them. */
function flatMatrix() {
	const { ex, ey } = flatFrame();
	const f = meta && meta.flat;
	return new THREE.Matrix4().makeBasis( ex, new THREE.Vector3( 0, 1, 0 ),
		ey.clone().negate() )
		.setPosition( new THREE.Vector3( ...( f ? f.origin : [ 0, 32, 0 ] ) ) );
}

/* Built for the unit that is open, and only for that one: seven of the
 * eight are never stood in, and the one that is is the only one a ceiling
 * belongs on. */
function roomShellSet( unit ) {
	if ( unit === roomShellUnit ) return;
	roomShellClear();
	roomShellUnit = unit;
	if ( unit < 0 || ! groups.flat || ! meta || ! meta.flat ) return;
	const mats = roomShellMats();
	const by = roomShellGeo( unit );
	const M = flatMatrix();
	roomShell = new THREE.Group();
	roomShell.name = 'room_shell';
	roomShell.visible = false;
	for ( const [ k, list ] of by ) {
		const mat = mats[ k ];
		if ( ! mat || ! list.length ) continue;
		let g = null;
		try { g = BufferGeometryUtils.mergeGeometries( list, false ); } catch ( e ) { g = null; }
		if ( ! g ) continue;
		list.forEach( x => x.dispose() );
		g.applyMatrix4( M );
		const mesh = new THREE.Mesh( g, mat );
		/* It receives, and it does not CAST. A ceiling that cast would
		 * take the sun off the floor of every room in the flat and leave
		 * the rooms with no windows - the hall, the bathroom - to be lit
		 * by nothing at all. What is wanted here is the light the open
		 * dollhouse already has, with something over it. */
		mesh.castShadow = false;
		mesh.receiveShadow = true;
		mesh.frustumCulled = false;
		roomShell.add( mesh );
	}
	groups.flat.add( roomShell );
}

/* On while the camera is under its own ceiling, which is exactly while it
 * is in a room. Checked on the frame rather than set at either end of the
 * dive, so it comes on halfway down the move: there the ceiling is edge on
 * to a camera passing through it and nobody sees it arrive. */
function roomShellStep() {
	if ( FLAT_GONE ) return lvInsideStep();
	const want = roomFocus >= 0 && !! roomShell
		&& camera.position.y < roomCeilingY() - 0.02;
	if ( want === roomShellOn ) return;
	roomShellOn = want;
	roomShell.visible = want;
	roomShadow( want );
	cityInside( want );
	invalidate( 2 );
}

/* ------------------------------------------- the sun's shadow, in a room
 * The sun's shadow is two cascades fitted to what the CAMERA sees, out to
 * `shadow.camera.far` - 420 m, because the street shot looks down a whole
 * avenue - and it is drawn once and kept. Both of those are right for the
 * street and both are wrong under a ceiling:
 *
 * - With a near plane of 0.25 m and a far one of 420 the split between the
 *   two cascades falls at about 110 m, so the WHOLE flat lies in the first
 *   and shares its 4096 texels with a hundred metres of nothing: three to
 *   five centimetres a texel. On a wall a metre from the eye that is a
 *   staircase down every shadow edge and a weave across every surface the
 *   sun grazes, which is what "it have pixels on shadows" was.
 * - The one redraw came from `cityInside`, at the instant the camera
 *   passed through the ceiling on its way down - so the cascades were
 *   fitted to a pose halfway through a dive and never to the room the
 *   visitor then stood and turned in.
 *
 * In a room the far plane is the length of a flat instead, which puts the
 * split at about 7 m and a texel at 2 mm in the near cascade and 6 mm in
 * the far one, and the map follows the camera: it is redrawn on the frames
 * the view moves and on no others (`frame` asks, off `viewMoved`), so a
 * visitor standing still pays nothing for it. What it draws while they
 * turn is the flat alone - the street is not in the scene under a ceiling,
 * see `cityInside`. ?roomshadow=0 keeps the street's map, =<metres> sets
 * the reach. */
const SHADOW_FAR = 420;
const ROOM_SHADOW = + ( __q.get( 'roomshadow' ) ?? 24 );
let roomShadowOn = false;
function roomShadow( inside ) {
	const want = inside && ROOM_SHADOW > 0;
	if ( want === roomShadowOn || ! sun || ! sun.shadow.camera ) return;
	roomShadowOn = want;
	sun.shadow.camera.far = want ? ROOM_SHADOW : SHADOW_FAR;
	shadowDirty();
}

/* ------------------------------------------ the city, from inside a room
 * A camera standing under its own ceiling cannot see the street, and
 * cannot see the storeys over it either - the only way out is the glazing,
 * and what is beyond that is a band of the building opposite in one door.
 *
 * It is not free to keep. Measured by tools/flatfill.cjs at 1600x900, in
 * the living room, with the density held still so every row is comparable:
 * the street and the tower are 74 of the frame's 240 draw calls and 3.5 of
 * its 7.4 M triangles, and taking them away moves the frame from a
 * swinging 72-98 ms to a steady 61 ms. The STEADINESS is worth as much as
 * the milliseconds - with them in, no two frames cost the same.
 *
 * And the milliseconds are not the point either: it is what they BUY. The
 * in-flat still frame supersamples out of a time budget divided by what a
 * pixel costs here (`stillScale`), so a cheaper pixel is a sharper
 * picture - 1.35x with the city in, the full 2x with it out, same machine,
 * same window. That is the parquet.
 *
 * The trade is the band through the loggia door, and `?city=1` keeps it.
 * Only while the camera is UNDER the ceiling: the storey seen from above,
 * and the flat open in the floor view, both stand in the street and keep
 * every bit of it. */
const CITY_INSIDE = ( new URLSearchParams( location.search ).get( 'city' ) ) === '1';
let cityHidden = false;
function cityInside( inside ) {
	const want = inside && ! CITY_INSIDE;
	if ( want === cityHidden ) return;
	cityHidden = want;
	if ( groups.main ) groups.main.visible = ! want;
	if ( groups.tower ) groups.tower.visible = ! want;
	/* The map is held for the life of the page, so the street going away
	 * under it would leave its shadow lying on the balcony. */
	shadowDirty();
	invalidate( 2 );
}

const roomCeilingY = () => {
	const f = meta && meta.flat;
	return ( f ? f.origin[ 1 ] : 31.8 ) + FM.TOP + floorDrop();
};

/* ------------------------------------------------------- the stance */
let roomFocus = - 1;             // which room the camera is in, or -1
let roomSaid = - 2;              // ...and what the page was last told
const ROOM_DUR = 1400;           // the dive in
const ROOM_STEP = 900;           // ...and the glide from one room to the next

const roomOwns = () => planDragOwns() && planFocus >= 0 && roomFocus >= 0;

function roomPose( unit, i ) {
	const R = ROOMS[ i ] || ROOMS[ 0 ];
	const p = roomWorld( unit, R.eye[ 0 ], R.eye[ 1 ], FM.FZ + R.h );
	const t = roomWorld( unit, R.at[ 0 ], R.at[ 1 ], FM.FZ + R.at[ 2 ] );
	const tmp = new THREE.PerspectiveCamera( R.fov, frameAspect(), 0.1, 4000 );
	tmp.position.copy( p );
	tmp.up.set( 0, 1, 0 );
	tmp.lookAt( t );
	return { p, q: tmp.quaternion.clone(), fov: R.fov, shift: 0, target: t };
}

/* Put the camera back on the stance after something has moved the window
 * under it. The ORIENTATION is kept unless it is asked for: by then the
 * visitor has very likely turned round, and a resize that puts them back
 * facing the way they came in is a resize that undoes their looking. */
function roomShot( aim = false ) {
	if ( roomFocus < 0 || planFocus < 0 ) return;
	// ...and once they have walked, where they are standing IS the shot
	if ( walkAim( aim ) ) return;
	const P = roomPose( planFocus, roomFocus );
	if ( ! aim ) P.q = camera.quaternion.clone();
	applyPose( P );
	if ( fly ) fly.sync();
}

/* The move in, the move out, and the step from one room to the next.
 *
 * In and out go over a CONTROL POINT standing directly above the room -
 * at the height the other end is at - so the camera slides across at
 * storey height and then drops down the room's own vertical, rather than
 * flying the straight line between the two. The straight line is a line
 * from 20 m over the street corner to a chair in the middle of the flat,
 * and it goes in through the gable: for a third of a second the window is
 * filled edge to edge with the inside of a wall. Down the vertical the
 * only thing it passes through is the ceiling, which it meets square on
 * and which is not there yet.
 *
 * A step from one room to the next is the straight line and nothing else.
 * Lifting out and dropping back in for a neighbouring room would be two
 * dives to look at the room next door; the glide through the wall between
 * them reads as a cut that has been shown its own way. */
function roomFly( to, dur, lift ) {
	const p0 = camera.position.clone(), q0 = camera.quaternion.clone();
	const fov0 = camera.fov, shift0 = camera.lensShift;
	planKillTween();
	camera.up.set( 0, 1, 0 );
	const c = lift === 'in' ? new THREE.Vector3( to.p.x, p0.y, to.p.z )
		: lift === 'out' ? new THREE.Vector3( p0.x, to.p.y, p0.z ) : null;
	tween( dur, 0, ( t ) => {
		const e = easeInOut( t );
		if ( c ) {
			const u = 1 - e, a = u * u, b = 2 * u * e, d = e * e;
			camera.position.set( a * p0.x + b * c.x + d * to.p.x,
				a * p0.y + b * c.y + d * to.p.y,
				a * p0.z + b * c.z + d * to.p.z );
		} else camera.position.lerpVectors( p0, to.p, e );
		/* The TURN runs on its own clock, a quarter of a beat behind the
		 * move going in and a quarter ahead of it coming out. Both ends
		 * of this flight look at the flat - straight down from over the
		 * storey, level from inside a room - and on one clock the camera
		 * is already level while it is still 15 m up, where level is the
		 * horizon and the flat is not in the picture at all. Behind, it
		 * keeps the plan in view all the way down the drop and comes
		 * level as it arrives; ahead, it is looking down at the flat
		 * before it has finished rising out of it. */
		const w = lift === 'in' ? ( t - 0.50 ) / 0.50
			: lift === 'out' ? t / 0.70 : t;
		const eq = easeInOut( Math.max( 0, Math.min( 1, w ) ) );
		camera.quaternion.slerpQuaternions( q0, to.q, eq );
		camera.fov = fov0 + ( to.fov - fov0 ) * eq;
		camera.lensShift = shift0 + ( to.shift - shift0 ) * eq;
		camera.updateProjectionMatrix();
		roomShellStep();
	}, () => {
		planTween = null;
		setMode( 'hero' );                 // lands it exactly, through `planShot`
		/* The fly controls carry their own yaw and pitch and only read the
		 * camera when they are switched on. The dive has turned it right
		 * round since, so without this the first drag in a room snaps the
		 * view back to whatever the floor was looking at. */
		if ( fly ) fly.sync();
		// ...and the visitor is standing on the stance it just landed on,
		// which from here is a body and not a camera
		walkEnter();
		// coming the other way, the doors have finished swinging back open
		// and the welded mesh can have them again
		if ( roomFocus < 0 ) doorRigClear();
		roomShellStep();
	} );
	planTween = tweens[ tweens.length - 1 ];
}

/* Walk into a room, step to the next one, or - with -1 - come back out to
 * the open flat.
 *
 * The dive in is the long move and a step from one room to the next is the
 * short one: both are straight lines, so the step passes through whatever
 * wall is between the two rooms. That is on purpose. An arc over the flat
 * would be a second dive every time somebody looks at the next room, and
 * the glide through reads as a cut that was shown its own way. */
function roomSet( i, animate = true ) {
	if ( ! planDragOwns() || planFocus < 0 ) return;
	const n = ( i >= 0 && i < ROOMS.length ) ? i | 0 : - 1;
	if ( n === roomFocus ) return;
	const inside = roomFocus >= 0;
	/* The three things a walked flat needs, all for the one unit and all
	 * built before the dive starts rather than when it lands: the shell
	 * over the rooms, the four doors on their hinges, and the floor plan
	 * the body cannot walk through. The dive is 1.4 s of camera move with
	 * nothing else to do, and rasterising the unit on the frame it arrives
	 * would be a hitch exactly where the visitor is looking hardest. */
	if ( n >= 0 ) {
		roomShellSet( planFocus );
		doorRigSet( planFocus );
	}
	// ...and walking stops for the flight, whichever way it is going
	walkOff();
	roomFocus = n;
	roomTell();
	const to = n >= 0 ? roomPose( planFocus, n ) : planFocusPose( planFocus );
	const lift = ( inside && n >= 0 ) ? null : n >= 0 ? 'in' : 'out';
	if ( animate ) roomFly( to, lift ? ROOM_DUR : ROOM_STEP, lift );
	else {
		applyPose( to );
		setMode( 'hero' );
		if ( fly ) fly.sync();
		if ( n >= 0 ) walkEnter();
		roomShellStep();
	}
	/* On the way out the shell goes at once rather than when the camera
	 * passes back up through the ceiling: the flight out is the plan
	 * coming back, and the last thing it may do is come back with a lid
	 * on it. */
	if ( n < 0 ) {
		roomShellOn = false;
		roomShadow( false );
		if ( roomShell ) roomShell.visible = false;
		/* ...and the doors swing back open behind them, to meet the pose
		 * the plan is drawn in. The rig itself goes when the flight lands
		 * - see `roomFly` - because until then it is what is drawing
		 * them. */
		doorRigOpen();
		if ( ! animate ) doorRigClear();
	}
	shadowDirty();
	invalidate();
}

function roomTell( force = false ) {
	const i = roomOwns() ? roomFocus : - 1;
	if ( ! force && i === roomSaid ) return;
	roomSaid = i;
	const was = sceneSettling;
	sceneSettling = true;
	try {
		announce( 'room', { room: i, key: i >= 0 ? ROOMS[ i ].key : null,
			name: i >= 0 ? ROOMS[ i ].name : null, count: ROOMS.length,
			unit: planFocus, floor: sceneFloor } );
	} finally { sceneSettling = was; }
}

/* ----------------------------------------------------------- the dots
 * One per room, standing over the middle of it. Projected off a point 1.2
 * m up rather than off the floor, for the same reason the area badges are:
 * the open flat is seen from 32 degrees off the vertical, and a dot on the
 * floor of a room stands on the wall in front of it. */
const _rq = new THREE.Vector3();
let roomDotSaid = '';
function roomDotTell( force = false ) {
	if ( FLAT_GONE ) return lvRoomDotTell( force );
	const f = meta && meta.flat;
	const live = planDragOwns() && planFocus >= 0 && roomFocus < 0 && !! f;
	if ( ! live ) {
		if ( roomDotSaid === '' ) return;
		roomDotSaid = '';
		announce( 'roomdot', { dots: [], on: false } );
		return;
	}
	const r = renderer.domElement.getBoundingClientRect();
	const out = [];
	for ( let i = 0; i < ROOMS.length; i ++ ) {
		const R = ROOMS[ i ];
		_rq.copy( roomWorld( planFocus, R.dot[ 0 ], R.dot[ 1 ], FM.FZ + 1.2 ) )
			.project( camera );
		out.push( {
			i, name: R.name, key: R.key,
			x: Math.round( ( _rq.x * 0.5 + 0.5 ) * r.width + r.left ),
			y: Math.round( ( - _rq.y * 0.5 + 0.5 ) * r.height + r.top ),
			// behind the camera, or off the plate: no dot to put anywhere
			on: _rq.z < 1 ? 1 : 0,
		} );
	}
	const key = out.map( p => p.x + ',' + p.y + ',' + p.on ).join( ';' );
	if ( ! force && key === roomDotSaid ) return;
	roomDotSaid = key;
	announce( 'roomdot', { dots: out, on: true } );
}

/* ------------------------------------------------------- the doors swing
 * A door in this flat is modelled OPEN - 68 to 84 degrees, which is the
 * pose the dollhouse and the floor view are shot in and the pose the sales
 * render has. Walked into, that is the one thing in the flat that is
 * obviously not real: every door in the place stands permanently ajar at
 * the same angle, and a visitor walks through four of them without one of
 * them moving.
 *
 * So the half of a door that hangs on its hinges - the leaf, its lipping
 * and the two lever handles - is its own object in the build
 * (`flat_door_<room>_swing__*`, see `lib_flat.door`), and nothing else is:
 * the lining, the architrave, the hinge barrels standing on the axis and
 * the striking plate in the far jamb all stay where they are. The page
 * welds the flat per material, so without that split there is no way to
 * turn a leaf without taking its own doorframe round with it.
 *
 * WHAT THE RIG DOES, when a flat is opened to be walked: it takes those
 * four doors of that one unit back out of the welded mesh, re-welds the
 * other seven units' worth without them, and hangs the four on pivots at
 * their own hinge lines. Then the whole flat's doors are shut, and each
 * one swings open as a body comes to it and stays open behind them, which
 * is both what a person does to a door and what leaves the flat in the
 * pose it is photographed in.
 *
 * It carries the leaf ABOVE THE CUT too. `lib_flat` stops the leaf at
 * 1.47 m with the walls, and the shell that carries the walls up past the
 * cut used to carry the leaf up with them - but a leaf in two halves can
 * only swing if one piece owns both, so the shell hands it over here.
 *
 * THE COST is three draw calls at rest - one per material, for all eight
 * units - and twelve more while a flat is being walked, where the shot is
 * parked and cheap. No new material and so no new pipeline: the swinging
 * halves are drawn in the same three materials as the frames they hang in.
 */

/* Which door, which of the eight units, and which material a node of the
 * build is the swinging half of - or null for the whole rest of the city.
 * The suffixes are `build_row`'s and `build_back_row`'s own: `_u1`..`_u3`
 * along the street and `_bk` for the line behind it, in that order. */
const DOOR_SWING = /^flat_(door_[a-z0-9]+)_swing__/;
function doorSwingOf( name ) {
	const m = DOOR_SWING.exec( name || '' );
	if ( ! m ) return null;
	let rest = name.slice( m[ 0 ].length ), col = 0, back = false;
	if ( rest.endsWith( '_bk' ) ) { back = true; rest = rest.slice( 0, - 3 ); }
	const u = /_u([123])$/.exec( rest );
	if ( u ) { col = + u[ 1 ]; rest = rest.slice( 0, - 3 ); }
	return { key: m[ 1 ].slice( 5 ), unit: col + ( back ? 4 : 0 ), mat: rest };
}

/* Every swinging half the build shipped, kept past the weld: one entry per
 * material, holding the mesh the weld made and that mesh's own pieces
 * keyed by unit and door. `doorRigSet` needs both - the pieces to hang,
 * and the mesh to re-weld without them. */
const doorSwing = new Map();          // material name -> { mesh, mat, full, by }

function doorStash( mesh, mat, geos, keys ) {
	const by = new Map();
	geos.forEach( ( g, i ) => {
		const k = keys[ i ];
		if ( k ) by.set( k.unit + '|' + k.key, g );
	} );
	doorSwing.set( mat.name, { mesh, mat, full: mesh.geometry, by } );
}

let doorRig = null, doorRigUnit = - 2;
const DOOR_NEAR = 1.55;          // how close a body comes before it opens
const DOOR_K = 34, DOOR_C = 12;  // the leaf's own spring: firm, and not quite bouncy

function doorRigClear() {
	if ( ! doorRig ) return;
	doorRig.traverse( ( o ) => { if ( o.isMesh ) o.geometry.dispose(); } );
	doorRig.removeFromParent();
	doorRig = null;
	doorRigUnit = - 2;
	// the welded mesh gets all eight units back
	for ( const S of doorSwing.values() ) {
		if ( S.mesh.geometry !== S.full ) S.mesh.geometry.dispose();
		S.mesh.geometry = S.full;
		S.mesh.visible = true;
	}
}

/* The leaf above the cut, in the flat's own plan: the piece `lib_flat`
 * stops at 1.47 and the piece the swing has to carry. Built flat along the
 * hinge - heading zero, a shut door - because the rig's pivot is what
 * turns it, and in the same two materials as the half underneath. */
function doorRigTop( D, m ) {
	const F = FM, out = [];
	const z0 = F.FZ, H = F.DOOR_H;
	const zb = Math.max( F.CUT, z0 + 0.010 ), zt = z0 + H - 0.006;
	if ( zt - zb < 1e-4 ) return out;
	const [ hx, hy ] = doorHinge( D );
	const th = 0.040, lw = D.w - 0.008;
	/* It GRIPS the half below it, 40 mm down into it, for the reason every
	 * other piece of the shell does: two faces in one plane at 1.47 is a
	 * hard line across every door in the flat, and the one thing a seam
	 * must not do is fall exactly where the cut was. */
	const slab = ( name, cu, len, wide ) => {
		const L = len - 0.002, W = wide - 0.002, zb_ = zb - 0.040;
		if ( L < 1e-4 || zt - zb_ < 1e-4 ) return;
		const g = new THREE.BoxGeometry( L, zt - zb_, W );
		/* position and normal and NOTHING else. These are welded onto the
		 * half of the leaf the build shipped, which the batching stripped
		 * to those two - and `mergeGeometries` answers a mismatch with a
		 * null and a line in the console, which is a door with no leaf. */
		g.deleteAttribute( 'uv' );
		// laid along the hinge from the hinge itself, which is the pivot
		g.translate( cu, ( zb_ + zt ) * 0.5, 0 );
		out.push( [ name, g ] );
	};
	slab( 'int_door_leaf', ( 0.004 + lw ) * 0.5, lw - 0.004, th );
	slab( 'int_white_gloss', lw + 0.002, 0.004, th );
	/* ...and into the world, turned the way a SHUT door lies: the pieces
	 * above are in the leaf's own length, and the rig turns them from
	 * there. The heading is the plan's, mirrored for the back line the
	 * same way every other heading in the flat is. */
	/* ...and into the model, turned to the angle the build MODELLED the
	 * leaf at rather than to a shut one: that is the pose the half below
	 * arrived in, and the pose the rig's own rotation is measured off. In
	 * the flat's basis z runs the other way, hence the sign on y - and the
	 * heading carries the back line's mirror with it. */
	const M = flatMatrix();
	const T = new THREE.Matrix4()
		.makeRotationY( doorHeading( D, m.back, D.angle ) )
		.premultiply( new THREE.Matrix4().makeTranslation( m.x( hx ), 0, - m.y( hy ) ) );
	return out.map( ( [ name, g ] ) => [ name, g.applyMatrix4( T ).applyMatrix4( M ) ] );
}

/* Hang the four doors of one unit. Everything is built in the model's own
 * world metres, so a pivot is a translation of the geometry off the hinge
 * and the same translation back on the object - and then `rotation.y`
 * about that point is the door opening. */
function doorRigSet( unit ) {
	if ( unit === doorRigUnit ) return;
	doorRigClear();
	doorRigUnit = unit;
	if ( unit < 0 || ! groups.flat || ! doorSwing.size || ! meta || ! meta.flat ) return;
	const m = roomMap( unit );
	doorRig = new THREE.Group();
	doorRig.name = 'door_rig';
	doorRig.doors = [];
	for ( const D of doorRows() ) {
		const [ hx, hy ] = doorHinge( D );
		const h = roomWorld( unit, hx, hy, 0 );        // the hinge, in the world
		const node = new THREE.Group();
		node.position.set( h.x, 0, h.z );
		const tops = doorRigTop( D, m );
		for ( const [ name, S ] of doorSwing ) {
			const g = S.by.get( unit + '|' + D.key );
			const add = tops.filter( t => t[ 0 ] === name ).map( t => t[ 1 ] );
			const list = ( g ? [ g.clone() ] : [] ).concat( add );
			if ( ! list.length ) continue;
			let merged = null;
			try { merged = BufferGeometryUtils.mergeGeometries( list, false ); }
			catch ( e ) { merged = null; }
			list.forEach( x => x.dispose() );
			if ( ! merged ) continue;
			merged.translate( - h.x, 0, - h.z );
			const mesh = new THREE.Mesh( merged, S.mat );
			mesh.castShadow = mesh.receiveShadow = true;
			mesh.frustumCulled = false;
			node.add( mesh );
		}
		if ( ! node.children.length ) continue;
		/* Shut and open, as world rotations about the hinge. They are
		 * derived from the plan headings rather than written down, so the
		 * leaf the rig turns and the leaf the body bumps into can never
		 * disagree - and the handedness of (ex, up, ey) never has to be
		 * reasoned about, because both ends go through the same map. */
		node.shut = doorYaw( D, m, 0 );
		node.open = doorYaw( D, m, D.angle );
		node.rotation.y = node.shut;
		node.t = 0;                 // 0 shut, 1 at the angle the build modelled
		node.v = 0;
		node.latched = false;       // ...and nobody has come to it yet
		node.D = D;
		// the middle of its opening, mapped: what a body walks AT
		const at = doorMiddle( D );
		node.world = [ m.x( at[ 0 ] ), m.y( at[ 1 ] ) ];
		doorRig.doors.push( node );
		doorRig.add( node );
	}
	// ...and the welded mesh loses this unit, so its doors are not drawn twice
	for ( const S of doorSwing.values() ) {
		const keep = [];
		for ( const [ k, g ] of S.by ) if ( + k.split( '|' )[ 0 ] !== unit ) keep.push( g );
		let rest = null;
		if ( keep.length ) {
			try { rest = BufferGeometryUtils.mergeGeometries( keep, false ); }
			catch ( e ) { rest = null; }
		}
		if ( S.mesh.geometry !== S.full ) S.mesh.geometry.dispose();
		S.mesh.geometry = rest || S.full;
		S.mesh.visible = !! rest;
	}
	groups.flat.add( doorRig );
}

/* A leaf `deg` degrees open, as a rotation about world +Y off the pose the
 * build modelled it in. `flatFrame`'s ex and ey are horizontal unit
 * vectors, so a plan heading is a world direction and the difference of
 * two of their yaws is the turn between them. */
function doorYaw( D, m, deg ) {
	const { ex, ey } = flatFrame();
	const yaw = ( th ) => {
		const x = ex.x * Math.cos( th ) + ey.x * Math.sin( th );
		const z = ex.z * Math.cos( th ) + ey.z * Math.sin( th );
		return Math.atan2( x, z );
	};
	let d = yaw( doorHeading( D, m.back, deg ) ) - yaw( doorHeading( D, m.back, D.angle ) );
	while ( d > Math.PI ) d -= Math.PI * 2;
	while ( d < - Math.PI ) d += Math.PI * 2;
	return d;
}

/* On the way out, every door is let go of at once. The flight out is 1.4 s
 * and the spring is under one, so by the time the camera is back over the
 * plan all four stand at the angle the build modelled them at - which is
 * the pose the dollhouse and the floor view are drawn in, and the pose the
 * welded mesh has when `doorRigClear` hands them back to it. Clearing the
 * rig outright instead would snap four shut doors open under a camera that
 * is still rising through the flat. */
function doorRigOpen() {
	if ( ! doorRig ) return;
	for ( const n of doorRig.doors ) n.latched = true;
}

/* Every door, every frame a visitor is walking. A door opens when a body
 * comes within reach of the middle of its opening and then STAYS open:
 * doors that shut themselves behind a visitor would be four rooms with the
 * lights going out one after another, and the flat is photographed with
 * all four standing open anyway. The leaf is sprung rather than tweened,
 * so it leaves the jamb hard and arrives soft, the way a pushed door does,
 * and it is snapped to its ends - a spring that is still settling by a
 * ten-thousandth is a page that never stops drawing. */
function doorRigStep( dt ) {
	if ( ! doorRig ) return false;
	let busy = false;
	for ( const n of doorRig.doors ) {
		const want = n.latched ? 1 : 0;
		if ( want === 1 || n.t > 0 || n.v !== 0 ) {
			const a = ( want - n.t ) * DOOR_K - n.v * DOOR_C;
			n.v += a * dt;
			n.t += n.v * dt;
			if ( n.t >= 1 ) { n.t = 1; n.v = 0; }
			if ( n.t < 0 ) { n.t = 0; n.v = 0; }
			if ( Math.abs( want - n.t ) < 1e-3 && Math.abs( n.v ) < 1e-3 ) {
				n.t = want; n.v = 0;
			} else busy = true;
			n.rotation.y = n.shut + ( n.open - n.shut ) * n.t;
		}
	}
	if ( busy ) invalidate( 2 );
	return busy;
}

/* How far a point in the plan is from the leaf of door `n` as it stands -
 * a body's own distance to a shut door, which is the only thing in the
 * flat that moves and so the one thing the grid below cannot carry. The
 * leaf is a segment from the hinge out along its heading. */
function doorLeafDist( n, m, x, y ) {
	const D = n.D;
	const [ hx, hy ] = doorHinge( D );
	const ax = m.x( hx ), ay = m.y( hy );
	const th = doorHeading( D, m.back, D.angle * n.t );
	const len = D.w - 0.008;
	const bx = ax + Math.cos( th ) * len, by = ay + Math.sin( th ) * len;
	const vx = bx - ax, vy = by - ay;
	const t = Math.max( 0, Math.min( 1,
		( ( x - ax ) * vx + ( y - ay ) * vy ) / ( vx * vx + vy * vy ) ) );
	return Math.hypot( x - ax - vx * t, y - ay - vy * t );
}

/* --------------------------------------------------------- walking it
 * Inside a flat the keys stop being a camera and become a person.
 *
 * The fly controls cross this flat in a second - 11 m/s, which is a drone
 * and not a viewing - climb through the ceiling on the space bar, and pass
 * through the bed. A visitor who has been walked down into a bedroom is
 * standing in a room, and from there the only honest thing the keys can be
 * is legs.
 *
 * THE BODY is a disc half a metre across whose eye is at the stance's own
 * height, and it answers to the keys the way legs do rather than the way a
 * thruster does: about a fifth of a second to get going and a seventh to
 * stop, 1.35 m/s at a walk and 2.4 with shift held, which is a brisk one.
 *
 * THE GAIT is clocked off the FLOOR, not off the clock: the phase advances
 * by the distance walked over the length of one pace, so the head drops on
 * a footfall at whatever frame rate the machine is managing, and a body
 * edging forward still takes whole steps. On top of that the head rises
 * and falls twice a stride, sways once, and carries a little roll with the
 * sway and a little nod with the fall - which is what a head on a spine
 * actually does, and the four together are the whole difference between a
 * camera being slid along the floor and somebody walking.
 *
 * All of it scales with how fast the body is going, and all of it SNAPS to
 * zero at the bottom: standing still is perfectly still, the frame is not
 * owed, and the page stops drawing. An idle breath would be lovely and
 * would cost the whole of render-on-demand, so there is not one.
 *
 * WHAT IT CANNOT WALK THROUGH is read off the model instead of being
 * written down here. The flat arrives WELDED - one mesh per material for a
 * whole row of flats, nothing left in it that knows a bed from a bathroom
 * - but every triangle is still there, and a body does not care which
 * piece it belongs to. So when a flat is opened, every triangle of that
 * unit between knee and chest height is rasterised into a 60 mm grid, and
 * the grid is turned into a distance field. A step is legal if it ends
 * further than a body's radius from anything solid.
 *
 * That is the whole collision model, and it costs nothing to keep: the
 * walls, the linings in them, the kitchen run, the beds, the bath, the
 * balcony glazing and the balcony rail all stop a body because they are
 * all in the model, and the rugs and the parquet do not because they are
 * under the band. Add a sofa in Blender and it stops a body too, with
 * nothing to change here. Writing the plan out by hand instead would have
 * been thirty numbers that drift the first time a partition moves.
 *
 * Per-triangle BOUNDING BOXES are filled rather than the triangles
 * themselves, which sounds crude and is exact for nearly all of this: the
 * flat is built out of axis-aligned boxes, and the two triangles of such a
 * box's face have the face for their bounding box. What over-fills is the
 * downloaded furniture, whose triangles are smaller than a cell anyway.
 *
 * SLIDING falls out of the same test: a step that fails is retried on each
 * axis alone, so a body walking into a wall at an angle runs along it
 * instead of stopping dead. And a body already inside something may
 * always move the way that gets it out - which is what the distance FIELD
 * is for rather than a plain solid-or-not. It has to be: the stances are
 * authored standing in corners, because a camera in the middle of a 3 m
 * room sees a wall, and several of them are closer to the plaster than a
 * shoulder is wide.
 *
 * THE DOORS are the one thing the grid cannot carry, because they move.
 * They are tested as a segment from the hinge along the leaf's own heading
 * at whatever angle it has got to, so a shut door is a wall and an open
 * one is a plank standing in the room beside its opening.
 */
const WK = {
	V: 1.35, RUN: 2.45,          // m/s, a walk and a brisk one
	TAU_UP: 0.19, TAU_DOWN: 0.13,   // how long the legs take to answer
	R: 0.24,                     // how much floor a body needs round it
	STEP: 0.76,                  // one pace
	BOB: 0.019, SWAY: 0.024,     // the head's rise and fall, and its sway
	ROLL: 0.012, NOD: 0.004,     // ...in radians, which is 0.7 and 0.2 degrees
	BAND: [ 0.25, 1.40 ],        // knee to chest, over the flat's own slab
	CELL: 0.06,                  // the grid the flat is rasterised into
	PAD: 0.6,                    // ...carried past the unit, so its walls are in it
	/* Under this the body has STOPPED, and is snapped to it. The decay is
	 * exponential and so never actually arrives, and a camera creeping by
	 * nanometres is a page that draws for ever: `viewMoved` cannot tell
	 * that kind of moving from the other kind. At 0.02 m/s the snap comes
	 * about half a second after the key goes up and throws away 3 mm of
	 * the coast, which is nothing against the 0.18 m it has already run. */
	STILL: 0.02,
};

/* `?walklog=1` reports what the rasteriser found, which is the one thing
 * about the walk that cannot be seen on the screen. */
const WKLOG = __q.get( 'walklog' ) === '1';

let walkOn = false;
const walk = { x: 0, y: 0, vx: 0, vy: 0, ph: 0, eye: 1.60,
	bobY: 0, sway: 0, roll: 0, nod: 0, map: null, balc: null };
let walkGrid = null;             // { nx, ny, x0, y0, cell, d } for the open unit
let walkGridUnit = - 2;

const _wd = new THREE.Vector3(), _wr = new THREE.Vector3();
const _wp = new THREE.Vector3(), _we = new THREE.Euler( 0, 0, 0, 'YXZ' );

/* ------------------------------------------------------- the floor plan
 * Every triangle of the open unit between knee and chest height, in the
 * flat's own plan, as a grid of solid cells. Built in `groups.flat`'s own
 * space rather than the world's, so the grid is the same on every storey
 * and the storey drop never enters into it. */
function walkRaster( unit ) {
	const f = meta && meta.flat, bx = planUnitBox( unit );
	if ( ! f || ! bx || ! groups.flat ) return null;
	const C = WK.CELL, P = WK.PAD;
	const x0 = bx.x0 - P, y0 = bx.y0 - P;
	const nx = Math.max( 1, Math.ceil( ( bx.x1 - bx.x0 + P * 2 ) / C ) );
	const ny = Math.max( 1, Math.ceil( ( bx.y1 - bx.y0 + P * 2 ) / C ) );
	const solid = new Uint8Array( nx * ny );
	const o = new THREE.Vector3( ...f.origin );
	const ex = new THREE.Vector3( ...f.ex ).normalize();
	const ey = new THREE.Vector3( ...f.ey ).normalize();
	const lo = o.y + WK.BAND[ 0 ], hi = o.y + WK.BAND[ 1 ];
	const inv = new THREE.Matrix4().copy( groups.flat.matrixWorld ).invert();
	const m1 = new THREE.Matrix4(), m2 = new THREE.Matrix4(), im = new THREE.Matrix4();
	let tris = 0, hit = 0, skip = 0;
	const t0 = performance.now();

	/* The whole row is welded into a handful of meshes, so there is no
	 * rejecting seven eighths of it by object: every triangle of all eight
	 * flats has to be looked at, and there are nearly two million of them.
	 * So the inner loop reads the position buffer straight rather than
	 * through `fromBufferAttribute` and `applyMatrix4`, skips the matrix
	 * entirely for the welded meshes - which are already in this group's
	 * own space and are most of the geometry - and throws a triangle away
	 * on the cheapest test that can throw it away: the height band first,
	 * which drops nine tenths of them, then across the row, which drops
	 * seven eighths of the rest. Only what survives both is projected into
	 * the plan and filled. Done the obvious way round this was 280 ms,
	 * which is a hitch exactly where the visitor is looking hardest.
	 *
	 * Triangles are filled by their BOUNDING BOX, which sounds crude and is
	 * exact for nearly all of this: the flat is built out of axis-aligned
	 * boxes, and the two triangles of such a box's face have that face for
	 * their box. What over-fills is the downloaded furniture, whose
	 * triangles are smaller than a cell anyway. */
	const xA = x0 - 0.5, xB = x0 + nx * C + 0.5;
	const vx = [ 0, 0, 0 ], vy = [ 0, 0, 0 ], vz = [ 0, 0, 0 ];

	const sweep = ( pos, idx, E, ident ) => {
		const inter = !! pos.isInterleavedBufferAttribute;
		const pa = inter ? pos.data.array : pos.array;
		const st = inter ? pos.data.stride : pos.itemSize;
		const of = inter ? pos.offset : 0;
		const ia = idx ? idx.array : null;
		const n = idx ? idx.count : pos.count;
		for ( let t = 0; t + 2 < n; t += 3 ) {
			tris ++;
			let ya = Infinity, yb = - Infinity;
			for ( let k = 0; k < 3; k ++ ) {
				const i = ( ia ? ia[ t + k ] : t + k ) * st + of;
				let X = pa[ i ], Y = pa[ i + 1 ], Z = pa[ i + 2 ];
				if ( ! ident ) {
					const a2 = E[ 0 ] * X + E[ 4 ] * Y + E[ 8 ] * Z + E[ 12 ];
					const b2 = E[ 1 ] * X + E[ 5 ] * Y + E[ 9 ] * Z + E[ 13 ];
					const c2 = E[ 2 ] * X + E[ 6 ] * Y + E[ 10 ] * Z + E[ 14 ];
					X = a2; Y = b2; Z = c2;
				}
				vx[ k ] = X; vy[ k ] = Y; vz[ k ] = Z;
				if ( Y < ya ) ya = Y;
				if ( Y > yb ) yb = Y;
			}
			if ( yb < lo || ya > hi ) { skip ++; continue; }
			/* Into the flat's own plan. ex and ey are horizontal, so the
			 * height plays no part and each is two multiplies. */
			let a = Infinity, b = - Infinity, c = Infinity, d = - Infinity;
			for ( let k = 0; k < 3; k ++ ) {
				const dx = vx[ k ] - o.x, dz = vz[ k ] - o.z;
				const u = dx * ex.x + dz * ex.z;
				if ( u < a ) a = u;
				if ( u > b ) b = u;
				const w = dx * ey.x + dz * ey.z;
				if ( w < c ) c = w;
				if ( w > d ) d = w;
			}
			if ( b < xA || a > xB ) { skip ++; continue; }
			let i0 = Math.floor( ( a - x0 ) / C ), i1 = Math.floor( ( b - x0 ) / C );
			let j0 = Math.floor( ( c - y0 ) / C ), j1 = Math.floor( ( d - y0 ) / C );
			if ( i1 < 0 || j1 < 0 || i0 >= nx || j0 >= ny ) continue;
			if ( i0 < 0 ) i0 = 0;
			if ( j0 < 0 ) j0 = 0;
			if ( i1 >= nx ) i1 = nx - 1;
			if ( j1 >= ny ) j1 = ny - 1;
			for ( let j = j0; j <= j1; j ++ ) solid.fill( 1, j * nx + i0, j * nx + i1 + 1 );
			hit ++;
		}
	};

	const IDENT = new THREE.Matrix4();
	for ( const top of groups.flat.children ) {
		// the shell and the rig are ours, not the build's: the shell stands
		// above the cut, and the leaves the rig holds are the one thing in
		// the flat that moves, so they are tested as they stand instead
		if ( top === roomShell || top === doorRig ) continue;
		top.traverse( ( ob ) => {
			if ( ! ob.isMesh ) return;
			const g = ob.geometry, pos = g && g.getAttribute( 'position' );
			if ( ! pos ) return;
			ob.updateWorldMatrix( true, false );
			m1.multiplyMatrices( inv, ob.matrixWorld );
			const idx = g.getIndex();
			if ( ob.isInstancedMesh ) {
				for ( let q = 0; q < ob.count; q ++ ) {
					ob.getMatrixAt( q, im );
					m2.multiplyMatrices( m1, im );
					sweep( pos, idx, m2.elements, false );
				}
			} else {
				const E = m1.elements;
				sweep( pos, idx, E, m1.equals( IDENT ) );
			}
		} );
	}

	/* ...and the grid becomes a distance field, so one lookup says how far
	 * a body standing there is from anything solid. Two chamfer passes,
	 * which is within a couple of per cent of the true distance and is the
	 * whole of it in linear time. Off the grid counts as solid: the edge of
	 * the rasterised unit is the edge of the world. */
	const d = new Float32Array( nx * ny );
	const INF = 1e6, D2 = Math.SQRT2;
	for ( let i = 0; i < d.length; i ++ ) d[ i ] = solid[ i ] ? 0 : INF;
	for ( let j = 0; j < ny; j ++ ) for ( let i = 0; i < nx; i ++ ) {
		const k = j * nx + i;
		if ( d[ k ] === 0 ) continue;
		let v0 = i === 0 ? 1 : d[ k - 1 ] + 1;
		if ( j > 0 ) {
			v0 = Math.min( v0, d[ k - nx ] + 1 );
			v0 = Math.min( v0, ( i === 0 ? 0 : d[ k - nx - 1 ] ) + D2 );
			v0 = Math.min( v0, ( i === nx - 1 ? 0 : d[ k - nx + 1 ] ) + D2 );
		} else v0 = Math.min( v0, 1 );
		if ( v0 < d[ k ] ) d[ k ] = v0;
	}
	for ( let j = ny - 1; j >= 0; j -- ) for ( let i = nx - 1; i >= 0; i -- ) {
		const k = j * nx + i;
		if ( d[ k ] === 0 ) continue;
		let v0 = i === nx - 1 ? 1 : d[ k + 1 ] + 1;
		if ( j < ny - 1 ) {
			v0 = Math.min( v0, d[ k + nx ] + 1 );
			v0 = Math.min( v0, ( i === nx - 1 ? 0 : d[ k + nx + 1 ] ) + D2 );
			v0 = Math.min( v0, ( i === 0 ? 0 : d[ k + nx - 1 ] ) + D2 );
		} else v0 = Math.min( v0, 1 );
		if ( v0 < d[ k ] ) d[ k ] = v0;
	}
	if ( WKLOG ) console.info( '[walk] unit', unit, nx + 'x' + ny, 'cells,',
		tris, 'triangles,', skip, 'rejected whole,', hit, 'in the band,',
		( performance.now() - t0 ).toFixed( 1 ), 'ms' );
	return { nx, ny, x0, y0, cell: C, d };
}

/* Kept per unit once it is built. Rasterising is a tenth of a second and
 * the answer never changes - the flat is the same flat on every storey,
 * because the grid is built in the group's own space and the storey drop
 * is outside it - so a visitor who closes a flat and opens it again, or
 * walks the same plan on another floor, pays for it once. Eight units at
 * 37 kB is the whole of the memory this costs. */
const walkGrids = new Map();

function walkGridSet( unit ) {
	if ( unit === walkGridUnit ) return;
	walkGridUnit = unit;
	if ( unit < 0 ) { walkGrid = null; return; }
	if ( ! walkGrids.has( unit ) ) walkGrids.set( unit, walkRaster( unit ) );
	walkGrid = walkGrids.get( unit );
}

/* How far the point is from anything solid, in metres. Bilinear, because
 * nearest-cell makes a diagonal wall a flight of 60 mm steps under the
 * feet - and off the grid is solid, so a body cannot leave the flat. */
function walkDist( x, y ) {
	const G = walkGrid;
	if ( ! G ) return 1e3;
	const fx = ( x - G.x0 ) / G.cell - 0.5, fy = ( y - G.y0 ) / G.cell - 0.5;
	const i = Math.floor( fx ), j = Math.floor( fy );
	const tx = fx - i, ty = fy - j;
	const at = ( a, b ) => ( a < 0 || b < 0 || a >= G.nx || b >= G.ny )
		? 0 : G.d[ b * G.nx + a ];
	return G.cell * ( at( i, j ) * ( 1 - tx ) * ( 1 - ty )
		+ at( i + 1, j ) * tx * ( 1 - ty )
		+ at( i, j + 1 ) * ( 1 - tx ) * ty
		+ at( i + 1, j + 1 ) * tx * ty );
}

/* ...and the same with the doors in it, which the grid cannot hold
 * because they are the one thing in the flat that moves. */
function walkFree( x, y ) {
	let d = walkDist( x, y );
	if ( doorRig && walk.map ) for ( const n of doorRig.doors ) {
		const t = doorLeafDist( n, walk.map, x, y ) - 0.02;   // half the leaf
		if ( t < d ) d = t;
	}
	return d;
}

/* A door opening against a body MOVES the body. Everything else in the
 * flat stands still, so being inside something can only happen two ways:
 * a leaf has swung through where somebody was standing, or they arrived
 * there. Both happen - the master's stance is authored inside its own
 * door's swing, because the door is MODELLED open and a camera put in the
 * corner of that room lands exactly where the leaf stands - and the honest
 * answer to both is the same: step out of its way.
 *
 * The push runs uphill in the same field the walk is tested against, so it
 * can never shove a body through a wall to get it clear of a door; the
 * worst it can do is stop. A few centimetres a frame, which over the
 * second a leaf takes to swing is a visitor stepping aside rather than
 * being shot across the room. */
function walkPush() {
	let d = walkFree( walk.x, walk.y );
	for ( let s = 0; s < 4 && d < WK.R; s ++ ) {
		const e = 0.03;
		const gx = walkFree( walk.x + e, walk.y ) - walkFree( walk.x - e, walk.y );
		const gy = walkFree( walk.x, walk.y + e ) - walkFree( walk.x, walk.y - e );
		const L = Math.hypot( gx, gy );
		if ( L < 1e-6 ) break;
		const step = Math.min( WK.R - d, 0.05 );
		const nx = walk.x + gx / L * step, ny = walk.y + gy / L * step;
		const nd = walkFree( nx, ny );
		if ( nd <= d + 1e-5 ) break;        // nowhere better to be: stay put
		walk.x = nx; walk.y = ny; d = nd;
	}
}

/* One substep. A step that lands in something is retried on each axis
 * alone, which is what makes a body run along a wall instead of stopping
 * against it; and a body that is already inside something may move
 * whichever way takes it further out. */
function walkTry( sx, sy ) {
	const d0 = walkFree( walk.x, walk.y );
	const ok = ( x, y ) => {
		const d = walkFree( x, y );
		return d >= WK.R || d > d0 + 1e-4;
	};
	if ( ok( walk.x + sx, walk.y + sy ) ) { walk.x += sx; walk.y += sy; return; }
	if ( sx && ok( walk.x + sx, walk.y ) ) { walk.x += sx; walk.vy = 0; return; }
	if ( sy && ok( walk.x, walk.y + sy ) ) { walk.y += sy; walk.vx = 0; return; }
	walk.vx = walk.vy = 0;
}

/* The balcony is tiled and stands 5 mm over the parquet, which is a step
 * nobody will see and the floor the body is actually standing on. */
function walkFloorH( x, y ) {
	const b = walk.balc;
	if ( b ) for ( const r of b )
		if ( x > r[ 0 ] && x < r[ 2 ] && y > r[ 1 ] && y < r[ 3 ] ) return FM.FZT;
	return FM.FZ;
}

/* Where the camera goes, given where the body is standing and where the
 * gait has got to. The look is the fly controls' own yaw and pitch - they
 * own the drag - with the gait's roll and nod laid on top, which is why
 * this writes the quaternion rather than letting them do it. */
function walkPlace() {
	const { ex, ey } = flatFrame();
	const f = meta && meta.flat;
	const o = f ? f.origin : [ 0, 32, 0 ];
	const h = walkFloorH( walk.x, walk.y ) + walk.eye + walk.bobY;
	_wp.set( o[ 0 ], 0, o[ 2 ] )
		.addScaledVector( ex, walk.x ).addScaledVector( ey, walk.y )
		.setY( o[ 1 ] + h + floorDrop() );
	if ( walk.sway ) _wp.addScaledVector( _wr, walk.sway );
	camera.position.copy( _wp );
	const L = fly.look;
	camera.quaternion.setFromEuler(
		_we.set( L.pitch + walk.nod, L.yaw, walk.roll, 'YXZ' ) );
}

/* The frame, when a visitor has the flat on foot. Returns true to tell the
 * fly controls it has taken their three axes off them. */
function walkStep( dt, f, r, fast, keys ) {
	if ( bwOn ) return bwStep( dt, f, r, fast, keys );
	if ( ! walkOn ) return false;
	// the doors have already moved this frame; anything they swept into
	// gets out of the way before the keys are read
	walkPush();
	/* Which way the body is facing: the camera's heading flattened onto
	 * the floor. A person walks where they are looking in plan, not down
	 * the view axis - pitched at the ceiling, WASD must still walk. */
	camera.getWorldDirection( _wd );
	_wd.y = 0;
	if ( _wd.lengthSq() < 1e-8 ) _wd.set( 0, 0, - 1 );
	_wd.normalize();
	_wr.crossVectors( _wd, camera.up ).normalize();

	const { ex, ey } = flatFrame();
	let tx = 0, ty = 0;
	if ( f || r ) {
		const wx = _wd.x * f + _wr.x * r, wz = _wd.z * f + _wr.z * r;
		const len = Math.hypot( wx, wz ) || 1;
		const sp = ( fast ? WK.RUN : WK.V ) / len;
		tx = ( wx * ex.x + wz * ex.z ) * sp;
		ty = ( wx * ey.x + wz * ey.z ) * sp;
	}
	const k = 1 - Math.exp( - dt / ( ( f || r ) ? WK.TAU_UP : WK.TAU_DOWN ) );
	walk.vx += ( tx - walk.vx ) * k;
	walk.vy += ( ty - walk.vy ) * k;
	/* Snapped at the bottom, or the exponential never quite arrives: a
	 * camera creeping by nanometres is a page that never stops drawing. */
	if ( Math.hypot( walk.vx, walk.vy ) < WK.STILL ) walk.vx = walk.vy = 0;

	// substepped finer than a cell, so a sprint cannot step over a wall
	const dist = Math.hypot( walk.vx, walk.vy ) * dt;
	const n = Math.max( 1, Math.ceil( dist / ( WK.CELL * 0.7 ) ) );
	for ( let s = 0; s < n; s ++ ) walkTry( walk.vx * dt / n, walk.vy * dt / n );

	// ---- the gait, clocked off the floor
	const sp = Math.hypot( walk.vx, walk.vy );
	const gait = Math.min( 1, sp / WK.V );
	if ( gait < 0.01 ) {
		walk.bobY = walk.sway = walk.roll = walk.nod = 0;
	} else {
		walk.ph += sp * dt / WK.STEP;
		const p = walk.ph * Math.PI * 2;              // one turn per pace
		walk.bobY = - WK.BOB * gait * Math.cos( p );  // lowest on a footfall
		walk.sway = WK.SWAY * gait * Math.sin( p * 0.5 );   // once a stride
		walk.roll = - WK.ROLL * gait * Math.sin( p * 0.5 );
		walk.nod = WK.NOD * gait * Math.cos( p );
	}

	// ---- and the doors it is walking at
	if ( doorRig ) for ( const d of doorRig.doors )
		if ( ! d.latched && Math.hypot( walk.x - d.world[ 0 ], walk.y - d.world[ 1 ] )
			< DOOR_NEAR ) d.latched = true;

	walkPlace();
	return true;
}

/* The visitor has arrived: take the stance the dive landed on as where the
 * body is standing. The eye is the stance's OWN height, not a nominal one,
 * so the first walking frame is exactly the frame the flight ended on and
 * nothing pops as the keys are handed over. */
function walkEnter() {
	/* The real building is walked by the walk module (web/walk.js), which
	 * hangs off `LVL.hooks` - `onRoom` says the camera has landed in a room,
	 * `shown()` / `groupOf()` hand it the level. Nothing to do here. */
	if ( FLAT_GONE ) { walkOn = false; if ( bwOn ) bwLanded(); else bwFromRoom(); return; }
	if ( roomFocus < 0 || planFocus < 0 ) { walkOn = false; return; }
	/* The floor plan is rasterised HERE, on the frame the dive lands,
	 * rather than on the frame it starts. It is a tenth of a second of
	 * arithmetic either way; at the start of the flight that is six
	 * dropped frames off a camera moving at its fastest, and at the end it
	 * is a stall against a camera that has already stopped, on a page that
	 * draws on demand and has nothing to draw. Nobody sees the second one. */
	walkGridSet( planFocus );
	const R = ROOMS[ roomFocus ], m = roomMap( planFocus );
	walk.map = m;
	walk.x = m.x( R.eye[ 0 ] );
	walk.y = m.y( R.eye[ 1 ] );
	walk.eye = R.h;
	walk.vx = walk.vy = 0;
	walk.ph = 0;
	walk.bobY = walk.sway = walk.roll = walk.nod = 0;
	/* The two loggias, mapped: the only floor in the flat that is not the
	 * parquet, and the only place a body can stand outside the rooms. */
	const F = FM, rect = ( a, b, c, d ) => {
		const xs = [ m.x( a ), m.x( c ) ], ys = [ m.y( b ), m.y( d ) ];
		return [ Math.min( ...xs ), Math.min( ...ys ),
			Math.max( ...xs ), Math.max( ...ys ) ];
	};
	walk.balc = [ rect( F.LOG_LIV, F.Y_FAC, F.LOG_LIV + F.LOG_OP, F.Y_LOG ),
		rect( F.LOG_BED, F.Y_FAC, F.LOG_BED + F.LOG_OP, F.Y_LOG ) ];
	walkOn = true;
	if ( fly ) fly.sync();
	walkPlace();
	invalidate();
}

function walkOff() {
	walkOn = false;
	walk.map = walk.balc = null;
}

/* Put the camera back where the body is after something has moved the
 * window under it - the one thing a resize must NOT do here is walk the
 * visitor back to the stance they came in on. `aim` re-aims as well, which
 * only the way in asks for. */
function walkAim( aim ) {
	if ( ! walkOn ) return false;
	if ( aim && roomFocus >= 0 ) {
		const P = roomPose( planFocus, roomFocus );
		camera.quaternion.copy( P.q );
		if ( fly ) fly.sync();
	}
	camera.up.set( 0, 1, 0 );
	camera.fov = ROOMS[ Math.max( 0, roomFocus ) ].fov;
	camera.aspect = frameAspect();
	camera.lensShift = 0;
	camera.updateProjectionMatrix();
	walkPlace();
	if ( controls ) controls.target.copy( camera.position )
		.addScaledVector( _wd.set( 0, 0, - 1 ).applyQuaternion( camera.quaternion ), 3 );
	return true;
}

/* ---------------------------------------------- the storey as a drawing
 * The floor view looks straight down on an open storey, and what a visitor
 * is there to do is READ PLANS - so the storey stops being a photograph
 * and becomes one. Every wall goes to ink, every floor to the brand's
 * amber, the lighting on both is flattened out, the glazing is taken out
 * and all the furniture with it: eight flats drawn in two colours, which
 * is what a plan has to be before it can be read at a glance.
 *
 * The furniture is not thrown away, it is PARKED. Each piece sits at zero
 * scale on its own foot, so hovering a flat grows it back out of the floor
 * it stands on - and the pieces do not all arrive together: the reveal is
 * a wipe across that flat, so the bed comes up, then the nightstand beside
 * it, then the rug. One flat at a time, the one under the pointer, and
 * everything else stays a drawing.
 *
 * All of it rides on materials that were already there. Nothing is split
 * into more objects and nothing is drawn twice: the flat costs the same 52
 * draw calls whether the storey is a drawing or a room.
 *
 *   WHICH of the eight units a fragment belongs to is read off its own
 *   position against the row's bay table, the way the lamps inside an
 *   opened storey already are - `row.starts` from the build, and the line
 *   the front and back rows meet on.
 *
 *   WHAT it is - wall, floor, furniture, glazing - is the MATERIAL's, not
 *   the fragment's. Four of the flat's materials build both the shell and
 *   the furniture in it (`chrome` is a tap and a window catch, oak is a
 *   bed and a window sill), and those four are copied so each copy has one
 *   job. The architecture always keeps the original, so the same material
 *   out in the city is never touched.
 *
 *   WHERE a piece's foot is rides in `apivot`, a vec3 baked into the
 *   furniture's geometry at load: the merge welds a whole row of bedrooms
 *   into one mesh, and without it a bed could only be scaled about the
 *   building's origin. It is on the furniture only - a fifth of the flat's
 *   vertices - because nothing else is ever moved.
 *
 *   WHEN a piece arrives falls out of where it stands in its own flat, so
 *   the stagger needs no per-piece bookkeeping at all: the same expression
 *   gives the shader its delay and the JS its delay for the instanced
 *   furniture, and the two agree without being told to.
 *
 * `?plan2d=0` turns the whole thing off and leaves the floor view the
 * furnished top-down shot it was. In developer mode it is off too: there
 * the flat is left unbatched so every piece can be picked and dragged, and
 * none of the welding this is built on has happened.
 * -------------------------------------------------------------------- */
const PLAN2D = __q.get( 'plan2d' ) !== '0';
/* Seconds: the storey draining to a drawing, filling back in, and a flat
 * furnishing under the pointer or going back to black when it leaves.
 * Leaving is quicker than arriving - a reveal that lingers after the
 * pointer has gone reads as lag, where one that arrives slowly reads as
 * deliberate. */
const PLAN_DRAIN = 1.0, PLAN_FILL = 0.45;
/* The hover is 0.8 s each way, on `easeInOut`. It used to leave in 0.30
 * against 0.85 arriving, on the argument that a reveal lingering after the
 * pointer has gone reads as lag - but a hover a visitor runs along a row of
 * eight flats wants one number, not two, and the ease is what takes the
 * snap off the short end rather than the seconds. */
const PLAN_IN = 0.8, PLAN_OUT = 0.8;
/* How far the rest of the storey stands back while one flat is open, and
 * how long it takes to get there. It is carried by the same `ink` the
 * drawing itself is - the open flat is not a drawing, so nothing of this
 * can touch it - which makes it one multiply in a shader that was already
 * doing that multiply, and no second pass over anything. ?focusdim= walks
 * it. */
const PLAN_DIM = Math.max( 0, Math.min( 0.92,
	+ ( new URLSearchParams( location.search ).get( 'focusdim' ) ?? 0.78 ) ) );
const PLAN_DIM_T = 0.55;
/* Of that, how much is SPREAD across the pieces rather than spent by all
 * of them at once. At 0 the flat furnishes in one blink; much past 1 and
 * the last chair is still arriving long after the first, which reads as a
 * slow page rather than as a flourish. */
const PLAN_SPREAD = 0.75;
/* ...and the wipe's own direction, as weights on the flat's two axes: a
 * little more along the row than into the plan, so it reads as a sweep
 * across the storey rather than a wave off the facade. */
const PLAN_WIPE_X = 0.58, PLAN_WIPE_Y = 0.42;
/* The time the drawing waits before it starts, so the storey is still a
 * building while the camera is leaving the street and the cut is still
 * travelling down it. A SHARE of that move rather than a fixed count of
 * seconds: shorten the step and the wait shortens with it, or the plan is
 * still a render once the camera has stopped over it. */
const PLAN_HOLD = FLOOR_IN / 1000 * 0.4;
const lin = ( h ) => {
	const n = parseInt( h.slice( 1 ), 16 );
	const f = ( v ) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow( ( v + 0.055 ) / 1.055, 2.4 ); };
	return [ f( ( n >> 16 ) & 255 ), f( ( n >> 8 ) & 255 ), f( n & 255 ) ];
};
/* The two tones the drawing is made of: the walls in ink and the floors in
 * the brand's amber, `--amber` in site.css, so the storey reads as a
 * drawing off the same sheet as the cards beside it rather than as a
 * greyed-out render.
 *
 * And it is drawn FLAT. The sun is still on the storey and would otherwise
 * lay the shadow of every wall across the floor it is standing on, which
 * is the one thing that stops a plan reading as a plan - so the two tones
 * go in as emission rather than as colour, and what is left of the
 * lighting is the sliver `PLAN_LIT` keeps, enough to tell the top of a
 * wall from its side and no more. The furniture arriving brings the whole
 * of the real shading back with it.
 *
 * All three are uniforms rather than constants, because what reads as ink,
 * as the brand's amber and as flat is a question about the grade and the
 * sun on the storey rather than about the hex, and it cannot be answered
 * away from the frame: `?ink=`, `?amber=` and `?flat=` set them for a
 * shot, and `__plantone()` walks them from the console over one boot. */
const PLAN_INK = uniform( new THREE.Vector3( ...lin( __q.get( 'ink' ) || '#0e0e11' ) ) );
/* Not `--amber` itself. The tone map desaturates anything bright and the
 * grade pulls the frame towards the photograph, so the brand's own hex
 * laid on flat comes back as sand - this is the hex that COMES OUT as the
 * brand's amber once both have had it, found by walking a ladder of them
 * against the badges standing on the same floor (`?amber=`, `?gain=`). */
const PLAN_AMBER = uniform( new THREE.Vector3( ...lin( __q.get( 'amber' ) || '#f2a500' ) ) );
const PLAN_LIT = uniform( 1 - ( + ( __q.get( 'flat' ) ?? 0.92 ) ) );
/* ...and how hard the amber is driven. The storey is under a navy scrim
 * that runs a third of the way across the plate and up its foot, and the
 * grade behind it pulls everything towards the photograph's own contrast,
 * so the brand's amber laid on at face value comes out as sand. This is
 * what puts the YELLOW back: the emission is driven past 1 so the colour
 * survives both and lands on the hex the cards beside it are using. */
const PLAN_GAIN = uniform( + ( __q.get( 'gain' ) ?? 0.70 ) );
window.__plantone = ( ink, amber, flat, gain ) => {
	if ( ink ) PLAN_INK.value.set( ...lin( ink ) );
	if ( amber ) PLAN_AMBER.value.set( ...lin( amber ) );
	if ( flat !== undefined && flat !== null ) PLAN_LIT.value = 1 - flat;
	if ( gain !== undefined && gain !== null ) PLAN_GAIN.value = gain;
	invalidate( 30 );
	return { ink, amber, flat, gain };
};

/* What a piece of the flat IS. The floors are named by their MATERIAL -
 * parquet, bathroom tiles and balcony tiling are floor whatever piece they
 * belong to - and everything else by the build's own node names, which is
 * the one place that knows a worktop from a wall. */
const PC_ARCH = 0, PC_FURN = 1, PC_FLOOR = 2, PC_GLAZE = 3;
const PC_NAME = [ 'ink', 'furn', 'floor', 'glaze' ];
const PC_FLOOR_MAT = /^(int_parquet|int_tile_floor|int_tile_white)$/;
const PC_FURN_NODE = new RegExp( '^flatm_|^flat_(bathtub|bed_|bench_|dining_'
	+ '|kitchen|lamp_|nightstand_|rug_|side_cabinet|towel_rail|tv_wall'
	+ '|vanity|wardrobe_|wc)' );

/* The build's own name for the piece a mesh belongs to. Walked up the way
 * `groupOf` walks it: a downloaded model arrives as a node with its
 * primitives underneath, and it is the node that is named. */
function planPieceName( o ) {
	for ( let n = o; n; n = n.parent ) if ( /^flat/.test( n.name || '' ) ) return n.name;
	return o.name || '';
}

function planClassOf( o ) {
	const mat = Array.isArray( o.material ) ? o.material[ 0 ] : o.material;
	if ( PC_FLOOR_MAT.test( ( mat && mat.name ) || '' ) ) return PC_FLOOR;
	const n = planPieceName( o );
	if ( /^flatx_/.test( n ) ) return PC_GLAZE;
	return PC_FURN_NODE.test( n ) ? PC_FURN : PC_ARCH;
}

/* Every uniform the drawing is driven by. They are all written from the
 * frame loop and nothing here is ever rebuilt, so turning a flat on and
 * off is a handful of floats and no shader work at all. */
const PL = {
	amt: uniform( 0 ),                            // 0 a room, 1 a drawing
	revA: uniform( new THREE.Vector4() ),         // how furnished each front unit is
	revB: uniform( new THREE.Vector4() ),         // ...and each one behind it
	seed: uniform( 0 ),                           // turns the dissolve's pattern
	o: uniform( new THREE.Vector3() ),            // the block's near corner
	ex: uniform( new THREE.Vector3( 1, 0, 0 ) ),  // along the street
	ey: uniform( new THREE.Vector3( 0, 0, 1 ) ),  // ...and into the plan
	cut: uniform( new THREE.Vector3() ),          // the three joints between the four units
	start: uniform( new THREE.Vector4() ),        // where each unit begins
	wide: uniform( new THREE.Vector4( 1, 1, 1, 1 ) ),  // ...and how wide it is
	mid: uniform( 9 ),                            // the line the two rows meet on
	deep: uniform( 9 ),                           // one row's own depth
	lo: uniform( new THREE.Vector3() ),           // the open storey, in its own frame
	hi: uniform( new THREE.Vector3() ),           // (x, y along the plan, z the height)
	dim: uniform( 0 ),                            // ...how far the REST of it stands back
};

/* The flat's frame, for a point given in it. Horizontal only, so it does
 * not matter whether the point arrives in world metres or in the group's
 * own - the flat is only ever moved in y. */
const planLocal = ( P ) => {
	const d = P.sub( PL.o );
	return [ dot( d, PL.ex ), dot( d, PL.ey ) ];
};

/* Which unit a point stands in, how far that unit is furnished, and where
 * the point falls in the wipe across it. One-hot over the four bays rather
 * than a divide, because the units are not equal: unit 0 is 11.84 m wide
 * where its copies are 11.54, and a nominal width walks half a metre out
 * by the end of the row. */
function planUnitAt( lx, ly ) {
	const a1 = atLeast( PL.cut.x, lx ), a2 = atLeast( PL.cut.y, lx ), a3 = atLeast( PL.cut.z, lx );
	const hot = vec4( oneMinus( a1 ), a1.sub( a2 ), a2.sub( a3 ), a3 );
	const back = atLeast( PL.mid, ly );
	const rev = dot( mix( PL.revA, PL.revB, back ), hot );
	const ux = saturate( lx.sub( dot( PL.start, hot ) ).div( dot( PL.wide, hot ) ) );
	// the back row read front-ways, so the wipe crosses both the same way
	const uy = saturate( mix( ly, PL.mid.mul( 2.0 ).sub( ly ), back ).div( PL.deep ) );
	return { rev, delay: saturate( ux.mul( PLAN_WIPE_X ).add( uy.mul( PLAN_WIPE_Y ) ) ) };
}

/* How far a piece has come, given its flat's dial and its own place in the
 * wipe. The spread is taken out of the front of the movement, so the flat
 * is always finished at 1 however much of it is staggered. */
const planProg = ( rev, delay ) => smoothstep( 0.0, 1.0,
	saturate( rev.mul( 1 + PLAN_SPREAD ).sub( delay.mul( PLAN_SPREAD ) ) ) );

/* The same arithmetic in JS, for the furniture that is instanced rather
 * than welded - it is scaled from here and faded in the shader, and the
 * two have to agree to the frame. */
const planProgJS = ( rev, delay ) => {
	const t = Math.max( 0, Math.min( 1, rev * ( 1 + PLAN_SPREAD ) - delay * PLAN_SPREAD ) );
	return t * t * ( 3 - 2 * t );
};

/* The dissolve. Interleaved gradient noise, turned every frame by `seed`,
 * exactly as the storey's own x-ray does it: what fades is the FRACTION of
 * a piece's fragments that are dropped rather than the alpha of each, so a
 * chair arriving costs no transparent pass and no sorting, and at rest the
 * frame is binary again. */
const planStip = ( () => {
	const p = screenCoordinate.xy;
	const g = p.x.mul( 0.06711056 ).add( p.y.mul( 0.00583715 ) ).add( PL.seed ).fract();
	return g.mul( 52.9829189 ).fract().mul( 0.96 ).add( 0.02 );
} )();

/* The open storey, for the materials the city shares with the flat: the
 * loggia concrete, the balcony rail, the window frames and the black
 * plaster all stand out in the street as well, and only the storey that
 * has been opened is a drawing. */
const planBox = ( lx, ly, y ) => atLeast( PL.lo.x, lx ).mul( atLeast( lx, PL.hi.x ) )
	.mul( atLeast( PL.lo.y, ly ) ).mul( atLeast( ly, PL.hi.y ) )
	.mul( atLeast( PL.lo.z, y ) ).mul( atLeast( y, PL.hi.z ) );

/* ------------------------------------------------------- the materials
 * One material, two jobs. Four of the flat's build both the shell and the
 * furniture standing in it, and the drawing has to take one away and leave
 * the other standing, so those four are COPIED - the copy shares the whole
 * node graph, so the two are the same surface and differ only in what the
 * floor view does to them. The architecture always keeps the original,
 * which is what keeps the city out of it: every material the street shares
 * with the flat is a shell material, and the shell is the class that never
 * moves. */
const planClass = new WeakMap();
function planSplitMaterials( root ) {
	if ( ! PLAN2D || DEV ) return;
	const seen = new Map();
	const flat = [];
	root.traverse( ( o ) => {
		if ( ! o.isMesh || Array.isArray( o.material ) || groupOf( o ) !== 'flat' ) return;
		const cls = planClassOf( o );
		flat.push( [ o, cls ] );
		if ( ! seen.has( o.material ) ) seen.set( o.material, new Set() );
		seen.get( o.material ).add( cls );
	} );
	const pick = new Map();
	for ( const [ mat, set ] of seen ) {
		// sorted, so PC_ARCH - 0 - is always the one that keeps the original
		[ ...set ].sort( ( a, b ) => a - b ).forEach( ( cls, i ) => {
			const m = i === 0 ? mat : mat.clone();
			if ( i ) m.name = mat.name + '__' + PC_NAME[ cls ];
			pick.set( mat.uuid + '|' + cls, m );
			planClass.set( m, cls );
		} );
	}
	/* Reassigned before the batching, so the merge keys do the splitting
	 * on their own: two classes of one material are two materials by the
	 * time anything is welded, and they land in two meshes. */
	for ( const [ o, cls ] of flat ) o.material = pick.get( o.material.uuid + '|' + cls );
}

/* A piece's own foot, written into every one of its vertices before the
 * weld swallows it. The geometry is already in the building's metres here,
 * so the pivot is too, and both are then carried down to the storey by the
 * group they hang in. Its FOOT and not its middle: furniture grows out of
 * the floor it stands on. */
function planBakePivot( geo ) {
	geo.computeBoundingBox();
	const b = geo.boundingBox;
	const px = ( b.min.x + b.max.x ) * 0.5, py = b.min.y, pz = ( b.min.z + b.max.z ) * 0.5;
	const n = geo.attributes.position.count;
	const a = new Float32Array( n * 3 );
	for ( let i = 0; i < n; i ++ ) { a[ i * 3 ] = px; a[ i * 3 + 1 ] = py; a[ i * 3 + 2 ] = pz; }
	geo.setAttribute( 'apivot', new THREE.BufferAttribute( a, 3 ) );
}

/* The furniture that keeps its own textures is INSTANCED rather than
 * welded - the chairs, the plants, the pillows and the cabinets, one mesh
 * for all eight flats - so it has no per-vertex pivot to be scaled about
 * and no room for one. It is scaled from here instead: each instance about
 * its own origin, which the build already put on its footprint at floor
 * level, which is the pivot wanted anyway. */
const planInst = [];
function planHoldInstanced( im ) {
	const m = new THREE.Matrix4();
	const rows = [];
	for ( let i = 0; i < im.count; i ++ ) {
		im.getMatrixAt( i, m );
		const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
		m.decompose( p, q, s );
		rows.push( { p, q, s, unit: - 1, delay: 0, at: 1 } );
	}
	planInst.push( { im, rows } );
}

function planPatch( m, cls, pivot, gate ) {
	if ( ! m || m.__plan ) return;
	m.__plan = true;
	const P = pivot ? attribute( 'apivot', 'vec3' ) : positionWorld;
	const [ lx, ly ] = planLocal( P );
	const U = planUnitAt( lx, ly );
	const amt = gate ? PL.amt.mul( planBox( lx, ly, P.y ) ) : PL.amt;
	if ( cls === PC_ARCH || cls === PC_FLOOR ) {
		/* The walls come back as one, not in the wipe: it is the furniture
		 * the stagger is for, and a flat whose walls arrive a corner at a
		 * time reads as a page loading. */
		const ink = amt.mul( oneMinus( smoothstep( 0.0, 0.55, U.rev ) ) );
		/* ...and with one flat open, the drawing around it stands back.
		 * `PL.dim` rides on `ink`, which is the drawing's own weight and
		 * is zero wherever a flat has been furnished - so the open flat
		 * cannot be touched by it however hard it is driven, and the storey
		 * it stands in goes quiet behind it. */
		const tone = ( cls === PC_ARCH ? PLAN_INK : PLAN_AMBER )
			.mul( oneMinus( PL.dim ) );
		/* Most of the tone goes in as EMISSION and only `PLAN_LIT` of it is
		 * left to be lit, so the storey comes out as the flat colour it is
		 * drawn in whatever the sun is doing to the roof around it. */
		const c = m.colorNode || vec3( m.color.r, m.color.g, m.color.b );
		m.colorNode = mix( c, tone.mul( PLAN_LIT ), ink );
		const e = m.emissiveNode || vec3( 0.0 );
		const glow = tone.mul( oneMinus( PLAN_LIT ) )
			.mul( cls === PC_ARCH ? float( 1.0 ) : PLAN_GAIN );
		m.emissiveNode = mix( e, glow, ink );
		// ...and a drawing has no gloss on it, or the sun finds the floor
		const r = m.roughnessNode || float( m.roughness );
		m.roughnessNode = mix( r, float( 0.97 ), ink );
		if ( m.metalnessNode || m.metalness )
			m.metalnessNode = mix( m.metalnessNode || float( m.metalness ), float( 0.0 ), ink );
		if ( m.clearcoatNode ) m.clearcoatNode = mix( m.clearcoatNode, float( 0.0 ), ink );
		return;
	}
	/* Furniture and glazing are taken out of the drawing altogether. The
	 * glazing goes with the walls, in one movement; the furniture goes
	 * with the wipe, and comes back SOLID well before it has finished
	 * growing - a chair that is still see-through at half size reads as a
	 * render that has not finished rather than as one arriving. */
	const vis = cls === PC_FURN
		? saturate( planProg( U.rev, U.delay ).mul( 2.4 ) )
		: smoothstep( 0.0, 0.5, U.rev );
	m.opacityNode = ( m.opacityNode || float( 1 ) )
		.mul( atLeast( planStip, mix( float( 1 ), vis, amt ) ) );
	m.alphaTest = 0.5;
	if ( cls === PC_FURN && pivot ) {
		const s = mix( float( 1 ), planProg( U.rev, U.delay ), amt );
		m.positionNode = positionLocal.sub( P ).mul( s ).add( P );
	}
}

/* Walked once, after the batching: what is in the flat now, which of it
 * carries a pivot, and which of its materials the city is also built from
 * - those are the ones whose patch has to be fenced to the open storey. */
function planSetupMaterials() {
	if ( ! PLAN2D || DEV || ! groups.flat ) return;
	const mine = new Map();                      // material -> does it carry apivot
	const inFlat = new Set();
	groups.flat.traverse( ( o ) => {
		if ( ! o.isMesh ) return;
		inFlat.add( o );
		const piv = !! o.geometry.getAttribute( 'apivot' );
		mine.set( o.material, ( mine.get( o.material ) ?? true ) && piv );
	} );
	const shared = new Set();
	scene.traverse( ( o ) => {
		if ( o.isMesh && ! inFlat.has( o ) && mine.has( o.material ) ) shared.add( o.material );
	} );
	for ( const [ m, piv ] of mine )
		planPatch( m, planClass.get( m ) ?? PC_ARCH, piv, shared.has( m ) );
}

/* The row, written out of the build's own bay table. Nothing here may
 * assume how wide a flat is: the bays move, and unit 0 is not the width of
 * its copies. */
function planSetupFrame() {
	const f = meta && meta.flat, b = meta && meta.block && meta.block.floors;
	if ( ! f || ! b || ! f.row ) return;
	PL.o.value.set( ...f.origin );
	PL.ex.value.set( ...f.ex ).normalize();
	PL.ey.value.set( ...f.ey ).normalize();
	const s = f.row.starts, end = f.row.end;
	PL.cut.value.set( s[ 1 ], s[ 2 ], s[ 3 ] );
	PL.start.value.set( s[ 0 ], s[ 1 ], s[ 2 ], s[ 3 ] );
	PL.wide.value.set( s[ 1 ] - s[ 0 ], s[ 2 ] - s[ 1 ], s[ 3 ] - s[ 2 ], end - s[ 3 ] );
	const depth = b.depth || 18;
	PL.mid.value = depth * 0.5;
	PL.deep.value = depth * 0.5;
	planPlaceBox();
}

/* ...and the storey it is open on, which moves with the scene. A little
 * proud of the flat at every edge, so a loggia rail or a window frame on
 * its outer face is inside the box rather than half in it. */
function planPlaceBox() {
	const f = meta && meta.flat, b = meta && meta.block && meta.block.floors;
	if ( ! f || ! b ) return;
	const y = f.floor + floorDrop();
	const end = ( f.row ? f.row.end : b.len ) + 0.6;
	PL.lo.value.set( - 0.6, - 0.6, y - 0.4 );
	PL.hi.value.set( end, ( b.depth || 18 ) + 0.6, y + b.h - 0.2 );
}

/* ------------------------------------------------------------ the hover
 * Which flat the pointer is on. The camera looks straight DOWN here, so
 * this is a ray against one horizontal plane rather than against the
 * storey: a plane through the middle of the rooms, not the floor, because
 * a plan read from 60 m up still has enough parallax for a pointer on a
 * far bed to fall on the floor of the flat behind it. */
const _plray = new THREE.Raycaster(), _plndc = new THREE.Vector2();
const _plplane = new THREE.Plane( new THREE.Vector3( 0, 1, 0 ), 0 );
const _plhit = new THREE.Vector3();
const _pld = new THREE.Vector3();
function planUnitUnder( px ) {
	const f = meta && meta.flat, b = meta && meta.block && meta.block.floors;
	if ( ! px || ! f || ! b || ! f.row ) return - 1;
	const r = renderer.domElement.getBoundingClientRect();
	_plndc.set( ( px[ 0 ] - r.left ) / r.width * 2 - 1,
		- ( ( px[ 1 ] - r.top ) / r.height ) * 2 + 1 );
	_plray.setFromCamera( _plndc, camera );
	_plplane.set( _plplane.normal.set( 0, 1, 0 ), - ( f.floor + floorDrop() + 1.1 ) );
	if ( ! _plray.ray.intersectPlane( _plplane, _plhit ) ) return - 1;
	_pld.copy( _plhit ).sub( PL.o.value );
	const lx = _pld.dot( PL.ex.value ), ly = _pld.dot( PL.ey.value );
	const s = f.row.starts, end = f.row.end, depth = b.depth || 18;
	if ( lx < s[ 0 ] || lx > end || ly < 0 || ly > depth ) return - 1;
	let col = 0;
	while ( col < 3 && lx >= s[ col + 1 ] ) col ++;
	return col + ( ly >= depth * 0.5 ? 4 : 0 );
}

/* ----------------------------------------------------------- the dials
 * Eight flats and the storey itself, all run off the frame loop rather
 * than the tween list - a tween in flight pauses the hero's rail, and
 * these have to be able to run while the camera is still flying in. */
const planDrawOwns = () => PLAN2D && ! DEV && !! groups.flat && ! FLAT_GONE
	&& sceneNo === 2 && scene2View === 'plan';
let planAmt = 0, planHold = 0, planHot = - 1, planDimAmt = 0;
/* How far each flat is furnished, and the plain SECONDS under it.
 *
 * `planRev` is the dial everything reads - the shader's `revA`/`revB` and
 * the instanced furniture's own copy of the same arithmetic - and it is
 * eased. `planRevT` is the clock, which is the only one of the two that can
 * be stepped by dt: an eased value cannot be advanced without un-easing it
 * first, so the two are kept side by side rather than one being recovered
 * from the other every frame.
 *
 * The ease is on the PLAYHEAD, not on the furniture. Each piece already
 * grows on its own smoothstep (`planProg`) - that is the shape of one chair
 * arriving, and it does not change. What eases now is the sweep across the
 * flat, so the stagger starts gently, runs, and settles. */
const planRev = [ 0, 0, 0, 0, 0, 0, 0, 0 ];
const planRevT = [ 0, 0, 0, 0, 0, 0, 0, 0 ];

/* ----------------------------------------------------------- the badges
 * Every flat in the drawing carries its area on it, in the middle of its
 * own plan. They are DOM, not geometry: the number has to be read at a
 * glance at whatever scale the row has been slid to, and a sprite in the
 * scene would be resampled by the temporal filter and the grade along with
 * everything else. So the scene says only WHERE each one goes and how far
 * its flat has been furnished - the page draws them.
 *
 * Projected from a point 1.2 m over each unit's own floor rather than off
 * its slab, so a badge sits on the ROOMS and not on a line of wall when
 * the plan is seen from a little off vertical. */
const _bq = new THREE.Vector3();
let planBadgeSaid = '';
function planBadgeTell( force = false ) {
	const f = meta && meta.flat, b = meta && meta.block && meta.block.floors;
	if ( ! f || ! b || ! f.row ) return;
	/* Off the floor view there is no plan for them to stand on. Said once
	 * rather than every frame, because the drawing draining away ends with
	 * a last write and that write must not leave eight invisible badges
	 * lying over the tour. */
	if ( ! planDrawOwns() ) {
		if ( planBadgeSaid === '' ) return;
		planBadgeSaid = '';
		announce( 'planbadge', { badges: [], on: false } );
		return;
	}
	const o = PL.o.value, ex = PL.ex.value, ey = PL.ey.value;
	const s = f.row.starts, end = f.row.end, depth = b.depth || 18;
	const y = f.floor + floorDrop() + 1.2;
	const r = renderer.domElement.getBoundingClientRect();
	const out = [];
	for ( let i = 0; i < 8; i ++ ) {
		const col = i & 3;
		const x0 = s[ col ], x1 = col < 3 ? s[ col + 1 ] : end;
		_bq.copy( o )
			.addScaledVector( ex, ( x0 + x1 ) * 0.5 )
			.addScaledVector( ey, depth * ( i < 4 ? 0.25 : 0.75 ) )
			.setY( y )
			.project( camera );
		out.push( {
			x: Math.round( ( _bq.x * 0.5 + 0.5 ) * r.width + r.left ),
			y: Math.round( ( - _bq.y * 0.5 + 0.5 ) * r.height + r.top ),
			/* On or off, not a fraction of the reveal. The badge is in the
			 * way of the rooms the hover is there to show, so it goes the
			 * moment the pointer lands rather than dissolving over the
			 * second the furniture takes to arrive - and it goes on the
			 * page's own ease, which is what makes it read as the badge
			 * stepping aside rather than as the plan fading. */
			on: ( planAmt > 0.5 && i !== planHot && planFocus < 0 ) ? 1 : 0,
		} );
	}
	/* A drag writes the pan sixty times a second and every announce is
	 * eight DOM writes at the other end, so it only goes out when something
	 * the page can SHOW has actually changed. */
	const key = out.map( p => p.x + ',' + p.y + ',' + p.on ).join( ';' );
	if ( ! force && key === planBadgeSaid ) return;
	planBadgeSaid = key;
	announce( 'planbadge', { badges: out, on: planDrawOwns() } );
}

/* Which flat is under the pointer. Asked once a frame off the same dirty
 * flag the street's storey hover is asked off, because the answer changes
 * when the plan SLIDES as well as when the pointer moves. */
function planHoverTest() {
	if ( FLAT_GONE ) return lvHoverTest();
	if ( ! planDrawOwns() ) return;
	// pinned to the open flat: see `planFocusSet`
	if ( planFocus >= 0 ) return;
	const n = planUnitUnder( floorPointer );
	if ( n === planHot ) return;
	planHot = n;
	invalidate( 2 );
}

let planSteps = 0, planPin = - 1;

/* Every dial out at once: the eight flats, the dissolve's phase, the
 * instanced furniture's matrices and the badges standing on the plan.
 *
 * `shadow` is the one piece a caller may hold back; see PLAN_SHADOW_MS. */
function planWrite( shadow = true ) {
	PL.revA.value.set( planRev[ 0 ], planRev[ 1 ], planRev[ 2 ], planRev[ 3 ] );
	PL.revB.value.set( planRev[ 4 ], planRev[ 5 ], planRev[ 6 ], planRev[ 7 ] );
	/* Turn the dissolve's pattern, for the same reason the storey's own
	 * opening turns it: a stipple that stands still is a screen door and
	 * the eye reads it as grain, where one that moves averages to a fade
	 * over the few frames the temporal filter holds. */
	PL.seed.value = ( PL.seed.value + 0.6180339887 ) % 1.0;
	planScaleInstanced();
	planBadgeTell();
	roomDotTell();
	/* The shadow map is drawn on demand here, and a bed that has gone
	 * still casting its shadow on the floor is the one thing that would
	 * give the whole trick away. */
	if ( shadow ) shadowDirty();
	invalidate( SETTLE );
}

/* How often the REVEAL may ask for that map, in milliseconds.
 *
 * The map is 4096 square over a 420 m frustum, and re-submitting the scene
 * into it is the difference between 402 draw calls and 208 - measured
 * interleaved by tools/planhover.cjs, where it ran to a tenth of the frame
 * and more. Asking for it on every frame of a hover spends that on
 * furniture a few texels across, thirty-odd times a second, for as long as
 * a visitor runs the pointer along the row.
 *
 * So the reveal asks at this rate instead, and ALWAYS on the frame a dial
 * lands: a chair that has finished growing and casts nothing is what would
 * give the trick away, where a chair whose shadow is a frame or two behind
 * it WHILE it grows is not. Every other caller of `planWrite` - the dev
 * pin, which is photographing a held frame - still gets the map at once. */
const PLAN_SHADOW_MS = 100;
let planShadowAt = 0;

/* Returns whether anything moved, which the frame loop needs to know: see
 * the density ladder in `frame()`. */
function planRevealStep( dt ) {
	planSteps ++;
	if ( planPin >= 0 ) return false;        // held still for a shot
	const live = planDrawOwns();
	if ( ! live ) planHot = - 1;
	else if ( planHold > 0 ) planHold = Math.max( 0, planHold - dt );
	// ...and whether one of them ARRIVED this frame, which the shadow needs
	let moved = false, landed = false;
	const want = ( live && planHold <= 0 ) ? 1 : 0;
	if ( planAmt !== want ) {
		const d = dt / ( want ? PLAN_DRAIN : PLAN_FILL );
		planAmt = want > planAmt ? Math.min( 1, planAmt + d ) : Math.max( 0, planAmt - d );
		PL.amt.value = planAmt;
		if ( planAmt === want ) landed = true;
		moved = true;
	}
	for ( let i = 0; i < 8; i ++ ) {
		const w = ( live && i === planHot ) ? 1 : 0;
		// the CLOCK is what is tested and stepped; the dial follows it
		if ( planRevT[ i ] === w ) continue;
		const d = dt / ( w ? PLAN_IN : PLAN_OUT );
		planRevT[ i ] = w > planRevT[ i ]
			? Math.min( 1, planRevT[ i ] + d ) : Math.max( 0, planRevT[ i ] - d );
		planRev[ i ] = easeInOut( planRevT[ i ] );
		if ( planRevT[ i ] === w ) landed = true;
		moved = true;
	}
	/* ...and the storey standing back behind an open flat. On its own ramp
	 * rather than the reveal's: the camera takes a second and a quarter to
	 * come down and this has to be done by the time it arrives, where the
	 * furniture is allowed to still be growing in. */
	const wantDim = ( live && planFocus >= 0 ) ? PLAN_DIM : 0;
	if ( planDimAmt !== wantDim ) {
		const d = dt / PLAN_DIM_T;
		planDimAmt = wantDim > planDimAmt
			? Math.min( wantDim, planDimAmt + d ) : Math.max( wantDim, planDimAmt - d );
		PL.dim.value = planDimAmt;
		if ( planDimAmt === wantDim ) landed = true;
		moved = true;
	}
	if ( ! moved ) return false;
	const now = performance.now();
	const shadow = landed || now - planShadowAt >= PLAN_SHADOW_MS;
	if ( shadow ) planShadowAt = now;
	planWrite( shadow );
	return true;
}

/* The instanced furniture, scaled about each piece's own origin. The unit
 * and the delay are worked out once, the first time the row is touched -
 * they are properties of where a chair STANDS, and nothing here ever moves
 * it. */
// scratch, so a reveal frame allocates nothing
const _pim = new THREE.Matrix4(), _pisc = new THREE.Vector3(), _pid = new THREE.Vector3();
function planScaleInstanced() {
	if ( ! planInst.length ) return;
	const f = meta && meta.flat, b = meta && meta.block && meta.block.floors;
	if ( ! f || ! f.row || ! b ) return;
	const s = f.row.starts, end = f.row.end, depth = b.depth || 18;
	const m = _pim, sc = _pisc, d = _pid;
	for ( const rec of planInst ) {
		let any = false;
		for ( const r of rec.rows ) {
			if ( r.unit < 0 ) {
				d.copy( r.p ).sub( PL.o.value );
				const lx = d.dot( PL.ex.value ), ly = d.dot( PL.ey.value );
				let col = 0;
				while ( col < 3 && lx >= s[ col + 1 ] ) col ++;
				const back = ly >= depth * 0.5;
				r.unit = col + ( back ? 4 : 0 );
				const w = ( col < 3 ? s[ col + 1 ] : end ) - s[ col ];
				const ux = Math.max( 0, Math.min( 1, ( lx - s[ col ] ) / w ) );
				const uy = Math.max( 0, Math.min( 1,
					( back ? depth - ly : ly ) / ( depth * 0.5 ) ) );
				r.delay = Math.min( 1, ux * PLAN_WIPE_X + uy * PLAN_WIPE_Y );
			}
			const e = 1 - planAmt + planAmt * planProgJS( planRev[ r.unit ], r.delay );
			if ( e !== r.at ) any = true;
			r.at = e;
		}
		if ( ! any ) continue;
		for ( let i = 0; i < rec.rows.length; i ++ ) {
			const r = rec.rows[ i ];
			sc.copy( r.s ).multiplyScalar( Math.max( r.at, 1e-4 ) );
			rec.im.setMatrixAt( i, m.compose( r.p, r.q, sc ) );
		}
		rec.im.instanceMatrix.needsUpdate = true;
	}
}

/* How wide the frame is right now. It is the photograph's 2048x1920 while the
 * wipe is up and the window's own shape once it is down, and every shot reads
 * it rather than assuming the reference's frame. */
const frameAspect = () => frameEl.clientWidth && frameEl.clientHeight
	? frameEl.clientWidth / frameEl.clientHeight : FRAME_AR;

function applyPose( P ) {
	camera.position.copy( P.p );
	camera.quaternion.copy( P.q );
	if ( P.up ) camera.up.copy( P.up ); else camera.up.set( 0, 1, 0 );
	camera.fov = P.fov;
	camera.aspect = frameAspect();
	camera.lensShift = P.shift;
	camera.updateProjectionMatrix();
	if ( controls ) controls.target.copy( P.target );
}

function flatShot() {
	applyPose( flatPose() );
}

/* Straight down on the flat, the facade at the top of the screen, framed so
 * the whole footprint fits. This is the view the plan overlay is for. */
function topShot() {
	const { c, ey } = flatFrame();
	const f = meta && meta.flat;
	const ar = frameAspect();
	const span = f ? Math.max( f.size[ 0 ], f.size[ 1 ] * ar ) : 12;
	const fov = 40;
	const h = ( span * 0.5 ) / Math.tan( fov * Math.PI / 360 ) / ar * 1.06;
	camera.position.set( c.x, c.y + h, c.z );
	camera.up.set( - ey.x, 0, - ey.z );          // facade at the top of the screen
	camera.lookAt( c.x, c.y, c.z );
	camera.fov = fov;
	camera.aspect = ar;
	camera.lensShift = 0;
	camera.updateProjectionMatrix();
	if ( controls ) controls.target.copy( c );
}

/* The whole top floor: our flat nearest and the three copies of it running
 * away east, seen down the line from beyond the gable so the row reads as a
 * row rather than as four plans side by side. The stand-off is a fraction of
 * the row's own length, so it still frames if the row grows or shrinks. */
function rowShot() {
	const { c, ex, ey } = flatFrame();
	const f = meta && meta.flat;
	const end = ( f && f.row ) ? f.row.end : ( f ? f.size[ 0 ] : 11.5 );
	const t = c.clone().addScaledVector( ex, end * 0.26 ).addScaledVector( ey, 0.6 );
	const p = t.clone().addScaledVector( ex, - end * 0.60 ).addScaledVector( ey, - end * 0.30 );
	p.y += end * 0.47;
	camera.position.copy( p );
	camera.up.set( 0, 1, 0 );
	camera.lookAt( t );
	camera.fov = 40;
	camera.aspect = frameAspect();
	camera.lensShift = 0;
	camera.updateProjectionMatrix();
	if ( controls ) controls.target.copy( t );
}

/* Which shot scene 2's locked Hero preset IS. A storey clicked on the
 * building opens the floor; every other way in - the tour button, a click on
 * the block that lands on no storey, the lab's own Scene 2 - opens the show
 * flat. It is held here rather than decided at the call site because
 * `setMode( 'hero' )` runs again at the end of every crane move and would
 * otherwise snap the camera back to the close shot on arrival. */
let scene2View = 'hero';
/* How much of the frame's left edge the PAGE is covering, in CSS pixels. The
 * floor view frames the storey in what is left rather than in the whole
 * window, so the block starts where the type rail ends instead of lying under
 * it. The page owns the number - it is the page's own furniture - and hands
 * it over through `LP.setInset`; the scene never reads the page's markup. */
let uiInset = 0;
/* ...and how far down the frame the page's cards begin, in the same CSS
 * pixels. The storey stands ON that line rather than in the middle of the
 * window: its top edge comes level with the top of the card grid, so the
 * plan and the cards start together and the rail's head sits over the clear
 * strip above both. Handed over by the page with the inset, for the same
 * reason - the scene never reads the page's markup. Zero means "centre it",
 * which is what the narrow layout and the lab both want. */
let uiTop = 0;
/* ...and how much of the frame's FOOT the page is covering, which only the
 * open flat reads. It is for the narrow layout, where the page is a band
 * across the window rather than a column beside it: there the card is
 * docked to the bottom and the flat is framed in what is left above it.
 * Zero everywhere else, which is every wide layout and the lab. */
let uiFoot = 0;
/* Which way up the floor view sits.
 *
 * It is the BLOCK's own axis, so the building lies square across the display
 * rather than cutting the picture corner to corner. But that axis has two
 * directions, and the wrong one turns the plan through 164 degrees - the
 * street ends up along the top of the frame and the whole scene spins through
 * it on the way up, which is what "dont make rotate" was about. So the half
 * that the camera is already facing wins, and the straighten is the 16
 * degrees between the street shot's heading and the building.
 *
 * Caught ONCE, in `setScene`, while the camera is still on the street and has
 * a heading to catch. `planPose` runs again on arrival - `setMode( 'hero' )`
 * ends every crane move and resets the shot - and by then the camera points
 * straight down with no heading left to read. */
const planUp = new THREE.Vector3( 0, 0, -1 );

function setPlanUp() {
	// the real building's plate lies along the plan's own x: up is its y
	const ey = ( FLAT_GONE && frameP ) ? frameP.ey : flatFrame().ey;
	const look = new THREE.Vector3();
	camera.updateMatrixWorld();
	camera.getWorldDirection( look );
	look.y = 0;
	planUp.set( ey.x, 0, ey.z ).normalize();
	if ( look.lengthSq() > 1e-6 && planUp.dot( look.normalize() ) < 0 ) planUp.negate();
}

function resetShot( keepRail = false ) {
	if ( sceneNo === 2 ) return bwOn ? bwPlace( bwS ) : scene2View === 'plan' ? planShot() : flatShot();
	if ( railOn() ) {
		/* Reset means the start of the sweep, running - EXCEPT for the
		 * camera that has just been flown back down to the street. That
		 * flight is aimed at `heroPose()`, which is the rail phase the
		 * visitor left from, so it lands exactly where it took off; this
		 * runs in its own callback, and winding the sweep back to zero
		 * here threw the camera off the shot it had just arrived at - it
		 * flew home, stopped, and then cut to somewhere else. Keep the
		 * phase and the snap is to where the camera already is. */
		if ( ! keepRail ) { railT = 0; railDir = 1; }
		railHoldUntil = 0; railTouchAt = - 1e9;
		const q = railPose( railT );
		camera.position.copy( q.p );
		camera.quaternion.copy( q.q );
		camera.up.set( 0, 1, 0 );
		camera.fov = FOV_Y;
		camera.aspect = frameAspect();
		camera.lensShift = HERO_SHIFT;
		camera.updateProjectionMatrix();
		railPin();
		if ( controls ) controls.target.copy( q.target );
		return;
	}
	const mh = metaHero();
	if ( mh ) {
		camera.position.copy( mh.p );
		camera.quaternion.copy( mh.q );
		camera.up.set( 0, 1, 0 );
		camera.fov = mh.fov;                    // FOV_Y, or a ?hero= candidate's
		camera.aspect = frameAspect();
		camera.lensShift = mh.shift;
		if ( mh.pan !== undefined ) camera.lensPan = mh.pan;
		camera.updateProjectionMatrix();
		if ( controls ) controls.target.copy( siteCenter() );
		return;
	}
	camera.position.set( 0, EYE, - HERO_PUSH );
	camera.up.set( 0, 1, 0 );
	camera.lookAt( 0, EYE, - HERO_PUSH - 1 );
	camera.fov = FOV_Y;
	camera.aspect = frameAspect();
	camera.lensShift = HERO_SHIFT;
	camera.updateProjectionMatrix();
	if ( controls ) controls.target.set( 10, 17, -95 );
}

/* ------------------------------------------------------- flying out loud
 * With the console open, the camera says where it is while you fly it:
 * throttled on the way, and once more the moment it stops - that last
 * line is the one worth keeping, because it is printed in the numbers
 * heroPose() and flatPose() are written in. ?flylog=0 silences it. */
const FLYLOG = ( new URLSearchParams( location.search ).get( 'flylog' ) ) !== '0';
const _fdir = new THREE.Vector3();
let flyLogAt = 0, flyLogOwed = false;

function flyPose() {
	const p = camera.position;
	camera.getWorldDirection( _fdir );
	const t = p.clone().addScaledVector( _fdir, 10 );
	return {
		x: + p.x.toFixed( 2 ), y: + p.y.toFixed( 2 ), z: + p.z.toFixed( 2 ),
		lookX: + t.x.toFixed( 2 ), lookY: + t.y.toFixed( 2 ), lookZ: + t.z.toFixed( 2 ),
		yaw: + ( Math.atan2( - _fdir.x, - _fdir.z ) * 180 / Math.PI ).toFixed( 1 ),
		pitch: + ( Math.asin( THREE.MathUtils.clamp( _fdir.y, - 1, 1 ) ) * 180 / Math.PI ).toFixed( 1 ),
		fov: + camera.fov.toFixed( 1 ), shift: + camera.lensShift.toFixed( 3 ),
		scene: sceneNo,
	};
}

function flyLog( what ) {
	const q = flyPose();
	console.log(
		`%c${ what }%c  pos ${ q.x }, ${ q.y }, ${ q.z }   look ${ q.lookX }, ${ q.lookY }, ${ q.lookZ }`
		+ `   yaw ${ q.yaw }\u00b0  pitch ${ q.pitch }\u00b0   fov ${ q.fov }  shift ${ q.shift }`,
		'color:#e5af69;font-weight:700', 'color:inherit' );
}

function flyReport( moved ) {
	if ( ! FLYLOG || ! fly.enabled ) { flyLogOwed = false; return; }
	const now = performance.now();
	if ( moved ) {
		flyLogOwed = true;
		if ( now - flyLogAt > 200 ) { flyLogAt = now; flyLog( 'fly' ); }
	} else if ( flyLogOwed ) {
		flyLogOwed = false; flyLogAt = now; flyLog( 'settled' );
	}
}

/* ---------------------------------------------------------------- loop */
/* Raise or lower the wipe. The frame itself never changes size - it is always
 * the whole window - but the bar has to be put back over the photograph's
 * band, so this goes through resize(). */
function setCompare( on ) {
	frameEl.classList.toggle( 'cmp', !! on );
	if ( renderer ) resize();
}

function resize() {
	const w = innerWidth, h = innerHeight;
	// The band of the frame the photograph occupies: full height, the
	// reference's own 2048x1920 shape, centred. The camera keeps the solved
	// vertical field and lens rise, so that band is the solved shot pixel for
	// pixel and the rest of the window is simply more sky and more street.
	const refW = h * FRAME_AR, refL = ( w - refW ) / 2;
	// the reference's own sampling density - 2048 px across that band, so a
	// 3 px window pane survives - but capped by a pixel budget, or a wide
	// window would quietly ask the GPU to shade twice the frame.
	const dense = IMG_W / refW;
	const budget = Math.sqrt( IMG_W * IMG_H * 1.15 / ( w * h ) );
	basePR = Math.min( 3.0, Math.max( devicePixelRatio, Math.min( dense, budget ) ) );
	renderer.setPixelRatio( currentPR() );
	renderer.setSize( w, h, false );
	renderer.domElement.style.width = w + 'px';
	renderer.domElement.style.height = h + 'px';
	frameEl.style.width = w + 'px';
	frameEl.style.height = h + 'px';
	frameEl.style.setProperty( '--refL', refL.toFixed( 1 ) + 'px' );
	frameEl.style.setProperty( '--refW', refW.toFixed( 1 ) + 'px' );
	placeSplit();
	camera.aspect = w / h;
	camera.updateProjectionMatrix();
	/* The plan shot is fitted to the frame's shape, so a window that changes
	 * shape has to be re-fitted. Every other preset survives on aspect alone.
	 * NOT while a scene change is being set up, though: `setCompare` calls
	 * `resize` from inside `setScene`, and re-shooting there parks the camera
	 * on the destination 4 ms after the click - `flyCamera` then takes that as
	 * its starting point and there is no flight left to make. */
	if ( sceneNo === 2 && scene2View === 'plan'
		&& ! tweens.length && ! sceneSettling ) planClamp();
	invalidate();
}

/* The wipe is held as a fraction of the photograph's band, not of the window,
 * so it stays where you left it when the window changes shape. */
function placeSplit() {
	const refW = parseFloat( frameEl.style.getPropertyValue( '--refW' ) ) || frameEl.clientWidth;
	const refL = parseFloat( frameEl.style.getPropertyValue( '--refL' ) ) || 0;
	frameEl.style.setProperty( '--split', ( refL + splitT * refW ).toFixed( 1 ) + 'px' );
}

let acc = 0, frames = 0;
const fpsEl = $( 'fps' );
/* what the last drawn frame was looking at, so a camera that has moved - by a
 * drag, by damping, by a flight - owes the next one */
const lastView = { p: new THREE.Vector3(), q: new THREE.Quaternion(), fov: 0, shift: 0 };

function viewMoved() {
	const moved = ! lastView.p.equals( camera.position )
		|| ! lastView.q.equals( camera.quaternion )
		|| lastView.fov !== camera.fov || lastView.shift !== camera.lensShift;
	if ( moved ) {
		lastView.p.copy( camera.position );
		lastView.q.copy( camera.quaternion );
		lastView.fov = camera.fov;
		lastView.shift = camera.lensShift;
	}
	return moved;
}

function setRenderScale( full ) {
	if ( full === fullRes || ! basePR ) return;
	fullRes = full;
	renderer.setPixelRatio( full ? basePR : basePR * MOVE_SCALE );
	renderer.setSize( innerWidth, innerHeight, false );
	renderer.domElement.style.width = innerWidth + 'px';
	renderer.domElement.style.height = innerHeight + 'px';
	setAoScale( full );
	if ( full ) invalidate( SETTLE );    // frames for the full-size resolve
}

function frame() {
	const dt = Math.min( clock.getDelta(), 0.05 );
	if ( controls.enabled ) controls.update();
	else if ( fly.enabled ) fly.update( dt );
	railStep( dt );
	const floorMoved = floorStep( dt );
	// the real building's storey bands, and its floor view's dials
	const bandMoved = FLAT_GONE ? lvBandStep( dt ) : false;
	planGlide( dt );
	const planMoved = planRevealStep( dt ) || ( FLAT_GONE && lvRevealStep( dt ) ) || bwLightStep( dt );
	doorRigStep( dt );
	const busy = tweens.length > 0;
	if ( busy ) invalidate( SETTLE );
	updateTweens();
	const shifted = viewMoved();
	// once a frame at most, whether the pointer moved or the camera did
	if ( floorDirty || ( shifted && floorPointer ) ) {
		floorDirty = false;
		floorTest();                 // which storey, on the street
		planHoverTest();             // ...and which flat, in the floor view
	}
	// the area badges ride the plan, so they move with the camera as well
	if ( shifted && planDrawOwns() ) planBadgeTell();
	if ( shifted && FLAT_GONE ) lvBadgeTell();
	// ...and so do the room dots on the open flat
	if ( shifted || busy ) { roomDotTell(); roomShellStep(); }
	// under a ceiling the sun's cascades are fitted to this view: see `roomShadow`
	if ( shifted && roomShadowOn ) shadowDirty();
	/* Everything that MOVES the picture says so here, not just the camera.
	 *
	 * The two hovers - the storey parting in the street, the flat
	 * furnishing in the floor view - run off this loop rather than off the
	 * tween list, on purpose: a tween in flight pauses the hero's rail, and
	 * a hover has to be able to answer while the camera is still flying in.
	 * The cost of that was that neither showed up in `shifted` or in
	 * `busy`, so as far as the density ladder was concerned a hovered page
	 * was a PARKED one - and it went on handing a parked shot's
	 * supersample, two and a quarter times the pixels, to an animation.
	 * Measured: 14 frames drawn for a 0.6 s reveal, 33 ms each, locked to
	 * half vsync. They are motion, and the ladder is told so. */
	const stirred = shifted || busy || planMoved || floorMoved || bandMoved;
	if ( stirred ) { moveFrames = MOVE_HOLD; stillFrames = 0; invalidate( SETTLE ); }
	else if ( moveFrames > 0 ) moveFrames --;
	// a shot that has stood still long enough to be worth supersampling
	else if ( stillFrames <= SS_DWELL && ++ stillFrames === SS_DWELL ) invalidate( SETTLE );
	flyReport( shifted || busy );
	if ( ADAPT ) applyScale();
	else if ( MOVE_SCALE < 1 ) setRenderScale( moveFrames === 0 );

	if ( compiling ) {                       // the renderer is lent out
		if ( ! compileSince ) compileSince = performance.now();
		else if ( bwOn && performance.now() - compileSince > BW_HOLD_CUE ) bwTell();
		return;
	}
	compileSince = 0;
	if ( owed <= 0 ) { fpsEl.textContent = 'idle'; acc = frames = 0; return; }
	owed --;
	pipeline.render();
	if ( ADAPT ) rate();
	__perf.rendered = ( __perf.rendered || 0 ) + 1;

	acc += dt; frames ++;
	if ( acc > 0.5 ) { fpsEl.textContent = ( frames / acc ).toFixed( 0 ) + ' fps'; acc = 0; frames = 0; }
}
