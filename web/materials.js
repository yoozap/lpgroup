// TSL node materials. The GLB only carries geometry plus a material *name* per
// surface; everything you actually see - the plaster grain, the concrete
// mottling, the asphalt, the glazing, the leaves - is built here procedurally
// so nothing depends on bitmap textures.
import {
	Fn, vec2, vec3, vec4, float, uniform, mix, min, max, abs, pow, clamp, dot,
	positionWorld, normalWorld, smoothstep, mx_fractal_noise_float, mx_noise_float,
	bumpMap, saturate, sub, mul, add, oneMinus, fract, sin, floor, length,
	cameraPosition, screenUV, screenCoordinate, step, select, normalLocal, time, exp,
	texture, cameraViewMatrix, normalize, frontFacing, vertexColor,
	cross, equirectUV, uv,
} from 'three/tsl';

const SR = ( h ) => {
	const n = parseInt( h.slice( 1 ), 16 );
	const f = ( v ) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow( ( v + 0.055 ) / 1.055, 2.4 ); };
	return [ f( ( n >> 16 ) & 255 ), f( ( n >> 8 ) & 255 ), f( n & 255 ) ];
};

/** fractal noise sampled in world space - our universal surface grain */
const grain = ( scale, oct = 4 ) =>
	mx_fractal_noise_float( positionWorld.mul( scale ), oct, 2.0, 0.5, 1.0 );

/** World space triplanar sample. Walls are vertical, roads are horizontal, and
 *  none of the merged geometry carries UVs, so every scanned map is projected
 *  on all three axes and blended by the surface normal. */
const triplanar = ( map, scale ) => {
	const p = positionWorld.mul( scale );
	const n = abs( normalWorld );
	const w = n.div( n.x.add( n.y ).add( n.z ).add( 0.0001 ) );
	return texture( map, p.yz ).rgb.mul( w.x )
		.add( texture( map, p.xz ).rgb.mul( w.y ) )
		.add( texture( map, p.xy ).rgb.mul( w.z ) );
};

const lum = ( c ) => c.r.mul( 0.30 ).add( c.g.mul( 0.59 ) ).add( c.b.mul( 0.11 ) );

/** Triplanar normal map, whiteout blend. Perturbs the world normal directly,
 *  so it needs neither UVs nor a tangent attribute on the merged geometry. */
const triplanarNormal = ( map, scale, strength ) => {
	const p = positionWorld.mul( scale );
	const n = abs( normalWorld );
	const w = n.div( n.x.add( n.y ).add( n.z ).add( 0.0001 ) );
	const bx = texture( map, p.zy ).xy.mul( 2.0 ).sub( 1.0 ).mul( strength );
	const by = texture( map, p.xz ).xy.mul( 2.0 ).sub( 1.0 ).mul( strength );
	const bz = texture( map, p.xy ).xy.mul( 2.0 ).sub( 1.0 ).mul( strength );
	const world = normalize( normalWorld
		.add( vec3( 0.0, bx.y, bx.x ).mul( w.x ) )
		.add( vec3( by.x, 0.0, by.y ).mul( w.y ) )
		.add( vec3( bz.x, bz.y, 0.0 ).mul( w.z ) ) );
	return normalize( cameraViewMatrix.transformDirection( world ) );
};

/** cheap hash from a world position, constant across one flat panel */
const panelHash = Fn( ( [ q ] ) => {
	const p = q.mul( 0.37 );
	return fract( sin( dot( p, vec3( 12.9898, 78.233, 37.719 ) ) ).mul( 43758.5453 ) );
} );

export function buildMaterials( THREE, opts ) {

	const { sunDir, sunColor, maps = {} } = opts;
	const SUN = uniform( new THREE.Vector3().copy( sunDir ) );
	const SUNC = uniform( new THREE.Color().copy( sunColor ) );
	const M = {};

	// ---------------------------------------------------------- plasters
	// the one render colour shared by the front wall and the west gable
	const RENDER_BLACK = '#18140f';
	/** Vertical weathering: splash dirt along the bottom of a wall plus slow
	 *  rain streaks running down it. Without these a render surface reads as
	 *  new plastic no matter how good the lighting is. */
	const weathering = ( baseH, strength ) => {
		const low = smoothstep( float( baseH ), float( 0.25 ), positionWorld.y );
		const splash = mx_fractal_noise_float(
			positionWorld.mul( vec3( 1.1, 0.25, 1.1 ) ), 4, 2.0, 0.5, 1.0 );
		const streak = mx_fractal_noise_float(
			positionWorld.mul( vec3( 2.6, 0.06, 2.6 ) ), 3, 2.0, 0.5, 1.0 );
		const run = saturate( streak.mul( 1.4 ).add( 0.15 ) ).mul(
			smoothstep( float( 0.0 ), float( 2.2 ), positionWorld.y.fract().oneMinus() ) );
		const dirt = saturate( low.mul( saturate( splash.mul( 1.3 ).add( 0.55 ) ) )
			.add( run.mul( 0.22 ) ) );
		return dirt.mul( strength );
	};

	/** Render / concrete. Procedural noise alone gives a surface that is too
	 *  even to read as a real wall, so a scanned map is projected triplanar on
	 *  top of it at two scales: once as fine grain, once as slow blotching.
	 *  Its mean is divided out so it adds texture without shifting the tone. */
	function renderPlaster( name, hex, rough, grainScale, grainAmt, bumpAmt,
		weather = 0.26, detail = 1.0, scan = 'concrete' ) {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = name;
		const base = vec3( ...SR( hex ) );
		const n1 = grain( grainScale, 5 );
		const n2 = grain( grainScale * 11.0, 3 );
		const blotch = grain( grainScale * 0.17, 3 );
		const patch = grain( grainScale * 0.055, 2 );

		let tint = float( 1.0 ).add( n1.mul( grainAmt ) )
			.add( blotch.mul( grainAmt * 2.2 ) ).add( patch.mul( grainAmt * 3.4 ) );
		let micro = float( 0.0 );
		let normalSet = false;

		// the scanned surface set this material borrows: the same asphalt maps
		// that drive the road, or the concrete wall scan
		const SCAN = scan === 'asphalt'
			? { d: maps.asphaltDiff, n: maps.asphaltNor, r: maps.asphaltRough,
				mean: 0.0535, tile: 2.4 }
			: { d: maps.concreteDiff, n: maps.concreteNor, r: maps.concreteRough,
				mean: 0.235, tile: 1.9 };

		if ( SCAN.d && detail > 0 ) {
			const fine = lum( triplanar( SCAN.d, 1.0 / SCAN.tile ) ).div( SCAN.mean );
			const slow = lum( triplanar( SCAN.d, 1.0 / ( SCAN.tile * 3.0 ) ) ).div( SCAN.mean );
			micro = fine.sub( 1.0 ).mul( 0.75 ).add( slow.sub( 1.0 ).mul( 0.95 ) );
			tint = tint.add( micro.mul( 0.40 * detail ) );

			if ( SCAN.n ) {
				m.normalNode = triplanarNormal( SCAN.n, 1.0 / SCAN.tile,
					float( Math.min( 2.4, 0.85 * detail ) ) );
				normalSet = true;
			}
		}

		const dirt = weathering( 7.0, weather );
		m.colorNode = base.mul( clamp( tint, 0.62, 1.40 ) )
			.mul( float( 1.0 ).sub( dirt.mul( 0.55 ) ) )
			.mul( mix( vec3( 1.0, 1.0, 1.0 ), vec3( 0.93, 0.95, 1.0 ), dirt ) );

		let rgh = float( rough ).add( n2.mul( 0.11 ) ).add( blotch.mul( 0.08 ) )
			.add( dirt.mul( 0.06 ) );
		if ( SCAN.r && detail > 0 ) {
			rgh = rgh.mul( 0.55 ).add(
				lum( triplanar( SCAN.r, 1.0 / SCAN.tile ) ).mul( 0.62 ) );
		}
		m.roughnessNode = clamp( rgh.add( micro.mul( 0.05 ) ), 0.25, 1.0 );

		if ( ! normalSet ) {
			m.normalNode = bumpMap(
				n1.mul( 0.45 ).add( n2.mul( 0.25 ) ).add( micro.mul( 0.9 * detail ) ),
				float( bumpAmt ) );
		}
		m.metalnessNode = float( 0.0 );
		return m;
	}

	M.plaster_dark = renderPlaster( 'plaster_dark', RENDER_BLACK, 0.90, 1.6, 0.085, 0.22, 0.26, 0.8 );

	/* The west gable is the one big flat surface you look straight at. It is
	 * the same render as the street facade - same colour, same grain - so it
	 * shares the material object outright rather than carrying a near-copy
	 * that would drift. (The photograph reads the gable lighter and warmer
	 * than the facade, 134/129/126 against 80/80/82, so a separate
	 * plaster_light at #d4be9a matched it to within a point; that is kept
	 * here for the record and is a one-line swap back.) */
	M.plaster_light = M.plaster_dark;
	// the wing's return wall stands in its own shadow and is lit by the sky
	// alone, which turned it blue-grey next to the sunlit facade; a touch
	// darker and warmer so both read as the same black plaster
	M.plaster_dark_b = renderPlaster( 'plaster_dark_b', '#130f0a', 0.90, 1.6, 0.085, 0.22, 0.26, 0.8 );

	M.concrete_loggia = renderPlaster( 'concrete_loggia', '#9b9386', 0.88, 2.2, 0.060, 0.20, 0.22, 0.9 );
	M.concrete_frame = renderPlaster( 'concrete_frame', '#867d72', 0.88, 2.0, 0.065, 0.18 );
	M.concrete_podium = renderPlaster( 'concrete_podium', '#a9a094', 0.86, 1.9, 0.075, 0.30, 0.3, 1.15 );
	M.stone_classical = renderPlaster( 'stone_classical', '#dbcfba', 0.89, 1.1, 0.055, 0.14 );
	M.stone_classical_b = renderPlaster( 'stone_classical_b', '#d2c6af', 0.90, 1.2, 0.06, 0.14 );
	M.curb = renderPlaster( 'curb', '#948e86', 0.85, 3.0, 0.09, 0.22 );
	M.sidewalk = ( () => {
		const m = renderPlaster( 'sidewalk', '#a39d95', 0.88, 2.6, 0.08, 0.2 );
		// paving joints
		const p = positionWorld.mul( vec3( 0.55, 0, 0.55 ) );
		const j = min( abs( fract( p.x ).sub( 0.5 ) ), abs( fract( p.z ).sub( 0.5 ) ) );
		const line = smoothstep( 0.0, 0.03, j );
		m.colorNode = m.colorNode.mul( mix( float( 0.78 ), float( 1.0 ), line ) );
		return m;
	} )();

	// ---------------------------------------------------------- asphalt
	// Scanned surface (PolyHaven "asphalt pit lane", 4 m tile) mapped straight
	// off world XZ, so the merged road needs no UVs. Two tile sizes are mixed
	// against a slow noise to kill the repeat, and a wide stain breaks the tone.
	M.asphalt = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'asphalt';
		const TILE = 4.0;
		const uvA = positionWorld.xz.mul( 1.0 / TILE );
		const uvB = positionWorld.xz.mul( 1.0 / ( TILE * 2.73 ) ).add( vec2( 0.37, 0.61 ) );
		const blend = saturate( grain( 0.021, 3 ).mul( 1.6 ).add( 0.5 ) );
		const wide = grain( 0.055, 4 );
		const fine = grain( 30.0, 2 );
		/* Wheel-polished bands: traffic burnishes a bright strip under each
		 * wheel track, and that banding along the street is a lot of what
		 * separates a road from a grey plane. Two things matter. The period is
		 * a real wheel-track spacing (3.2 m), not the 1.75 m first tried - too
		 * tight and the bands land under a pixel down the street and alias
		 * into scratches. And they fade out past about 40 m for the same
		 * reason. The street runs along Blender +x of block A, which is this
		 * direction once glTF has turned the scene Y-up. */
		const across = positionWorld.x.mul( 0.801 ).add( positionWorld.z.mul( 0.599 ) )
			.add( grain( 0.010, 2 ).mul( 0.9 ) );
		const cell = abs( fract( across.mul( 1 / 3.2 ) ).sub( 0.5 ) ).mul( 2.0 );
		const near = smoothstep( float( 72.0 ), float( 16.0 ),
			length( positionWorld.xz.sub( cameraPosition.xz ) ) );
		const polish = smoothstep( float( 0.0 ), float( 0.46 ), cell ).oneMinus()
			.mul( saturate( grain( 0.08, 3 ).mul( 0.7 ).add( 0.70 ) ) ).mul( near );

		if ( maps.asphaltDiff ) {
			const dA = texture( maps.asphaltDiff, uvA ).rgb;
			const dB = texture( maps.asphaltDiff, uvB ).rgb;
			const scan = mix( dA, dB, blend );
			// the scan is a near-black fresh surface; a city carriageway is a
			// worn, neutral grey, so lift it and pull most of the brown out
			const grey = scan.r.mul( 0.33 ).add( scan.g.mul( 0.52 ) ).add( scan.b.mul( 0.15 ) );
			// a city carriageway is warm, not blue: the photograph reads
			// R/B 1.06 where a straight desaturation of the scan gives 0.95
			const neutral = mix( scan, vec3( grey.mul( 1.14 ), grey, grey.mul( 0.84 ) ), 0.75 );
			const wear = saturate( grain( 0.30, 4 ).mul( 0.9 ).add( 0.5 ) );
			m.colorNode = neutral
				.mul( float( 0.51 ) )
				.mul( clamp( float( 0.90 ).add( wide.mul( 0.30 ) ).add( wear.mul( 0.22 ) ), 0.62, 1.55 ) )
				.mul( float( 1.0 ).add( polish.mul( 0.11 ) ) );
		} else {
			m.colorNode = vec3( ...SR( '#3c3b3d' ) )
				.mul( clamp( float( 1.0 ).add( fine.mul( 0.22 ) ).add( wide.mul( 0.3 ) ), 0.6, 1.5 ) );
		}

		if ( maps.asphaltRough ) {
			const rA = texture( maps.asphaltRough, uvA ).r;
			const rB = texture( maps.asphaltRough, uvB ).r;
			m.roughnessNode = clamp( mix( rA, rB, blend ).mul( 0.94 ).add( wide.mul( 0.10 ) )
				.sub( polish.mul( 0.07 ) ), 0.26, 1.0 );
		} else {
			m.roughnessNode = clamp( float( 0.70 ).add( wide.mul( 0.22 ) ), 0.3, 0.95 );
		}

		if ( maps.asphaltNor ) {
			// the carriageway is flat, so the tangent frame is just world X/Z:
			// no UV or tangent attribute needed on the merged geometry
			const nA = texture( maps.asphaltNor, uvA ).xyz.mul( 2.0 ).sub( 1.0 );
			const nB = texture( maps.asphaltNor, uvB ).xyz.mul( 2.0 ).sub( 1.0 );
			const n = mix( nA, nB, blend ).mul( vec3( 0.7, 0.7, 1.0 ) );
			const world = normalize( vec3( n.x, n.z, n.y.negate() ) );
			m.normalNode = normalize( cameraViewMatrix.transformDirection( world ) );
		} else {
			m.normalNode = bumpMap( fine, float( 0.22 ) );
		}
		m.metalnessNode = float( 0.0 );
		return m;
	} )();

	M.road_paint = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'road_paint';
		const wear = grain( 7.0, 4 );
		const scuff = saturate( grain( 1.7, 4 ).mul( 1.3 ).add( 0.52 ) );
		m.colorNode = vec3( ...SR( '#d6d3cb' ) )
			.mul( clamp( float( 0.62 ).add( wear.mul( 0.44 ) ), 0.28, 1.0 ) )
			.mul( mix( float( 0.66 ), float( 1.0 ), scuff ) );
		m.roughnessNode = clamp( float( 0.66 ).add( wear.mul( 0.25 ) ), 0.3, 1.0 );
		return m;
	} )();

	M.grass = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'grass';
		const n = grain( 3.2, 5 );
		m.colorNode = mix( vec3( ...SR( '#43561f' ) ), vec3( ...SR( '#6d7f37' ) ), saturate( n.mul( 0.9 ).add( 0.5 ) ) );
		m.roughnessNode = float( 0.92 );
		m.normalNode = bumpMap( grain( 24.0, 2 ), float( 0.5 ) );
		return m;
	} )();

	// ---------------------------------------------------------- glazing
	/* Almost nothing you see in a window belongs to the window. Three things
	 * arrive at the eye at once, and a pane that reads as glass is those
	 * three layered in the right proportion:
	 *
	 *  1  the sky, mirrored off the outer surface. At the grazing angles a
	 *     street facade is seen from, Fresnel pushes this to most of the
	 *     signal - which is why real glazing goes near white in a photograph,
	 *     and why a dark pane always reads as a hole punched in the wall.
	 *  2  the room behind, seen *with parallax*. A blind painted flat on the
	 *     pane travels with the camera, and that is the whole of the sticker
	 *     look; a real blind hangs 70 mm behind the glass and a real back
	 *     wall 4 m behind that, and both slide against the frame as you move.
	 *  3  the pane itself: the grime on it, and the bow every sealed unit has.
	 *
	 * The material stays **opaque**. Real transmission would want the scene
	 * re-rendered behind 1900 panes, would not survive the weld into one mesh
	 * per material, and would buy nothing - you cannot see into a room from
	 * across a street. What you can see is the *geometry* of the room, and
	 * interior mapping gives that for three divides.
	 */

	/** Sky radiance along a direction, read off the same equirectangular
	 *  Preetham texture the scene uses as its background and, through PMREM,
	 *  as its IBL - with the same projection, so a reflection and the light
	 *  coming in through a window agree with everything else in the frame. */
	const skyAt = ( dir ) => maps.sky
		? texture( maps.sky, equirectUV( normalize( dir ) ) ).rgb
		: vec3( 0.40, 0.42, 0.46 );

	const UP = vec3( 0.0, 1.0, 0.0 );
	/* The sun's irradiance over pi: an interior surface turned straight at
	 * the sun returns albedo * this. It is the SunLight intensity set in
	 * index.html, the one number about the scene this file has to be told
	 * twice - everything else about the lighting it reads off the sky. */
	const SUN_E = 5.4 / Math.PI;

	/** one integer cell -> one uniform random, constant across a whole room */
	const cellRand = ( id, seed ) => fract(
		sin( dot( id.add( float( seed ) ), vec3( 127.1, 311.7, 74.7 ) ) ).mul( 43758.5453 ) );

	/** signed, never zero - so a ray exactly parallel to a wall cannot divide
	 *  by nothing and take the whole pane with it */
	const nonzero = ( a ) => a.greaterThanEqual( 0.0 )
		.select( max( a, 1e-3 ), min( a, -1e-3 ) );

	/* Interior mapping (Joost van Dongen, 2008). The view ray is intersected
	 * with a box behind the pane analytically - no loop, no texture, no extra
	 * geometry - and whichever face it lands on is shaded. Everything happens
	 * in a basis taken from the surface normal rather than from the world
	 * axes, so it follows both blocks' bearings, every return, and the
	 * recessed loggia glazing without being told about any of them.
	 *
	 * The box grid is the building's own: a floor every `pitch` from the
	 * first slab at `base`, and a party wall every `w`. The panes run
	 * 0.05-2.65 m above each slab and the ceiling sits at 2.70, so a ceiling
	 * plane never cuts a pane - while a party wall sometimes does, which is
	 * what happens in a real building too.
	 */
	function interiorRoom( cfg, V, dist ) {
		const P = positionWorld;
		const N = normalWorld;
		// pane basis: `right` runs along the facade, +depth runs into the room
		const right = normalize( cross( UP, N ).add( vec3( 1e-4, 0.0, 0.0 ) ) );
		// the view ray in that basis, pointing inward. The depth component is
		// held off zero: at a grazing angle the ray hits a party wall almost
		// at once, which is exactly what you see looking along a facade.
		const dX = dot( V, right ).negate();
		const dY = V.y.negate();
		const dZ = max( dot( V, N ), 0.02 );
		// where it enters, inside its own room cell
		const cu = dot( P, right ).div( cfg.w );
		const cv = P.y.sub( cfg.base ).div( cfg.pitch );
		const x0 = fract( cu ).mul( cfg.w );
		const y0 = fract( cv ).mul( cfg.pitch );      // 0 at the slab
		// one identity per room: its cell, plus which facade plane it sits on
		// (dot(P,N) is constant across a wall), so two parallel walls of the
		// same block never hand out the same room twice
		const id = vec3( floor( cu ), floor( cv ),
			floor( dot( P, N ).mul( 0.37 ).add( 0.137 ) ) );
		const rA = cellRand( id, 0.0 );          // what is hanging in it
		const rB = cellRand( id, 13.7 );         // wall paint
		const rC = cellRand( id, 71.3 );         // blind drop, fold phase
		const rD = cellRand( id, 37.1 );         // floor, and the light on

		// ---- the box ----------------------------------------------------
		const sX = nonzero( dX ), sY = nonzero( dY );
		const tX = max( float( cfg.w ).sub( x0 ).div( sX ), x0.negate().div( sX ) );
		const tY = max( float( cfg.ceil ).sub( y0 ).div( sY ), y0.negate().div( sY ) );
		const tZ = float( cfg.depth ).div( dZ );
		const t = min( min( tX, tY ), tZ );
		const hx = x0.add( dX.mul( t ) );
		const hy = y0.add( dY.mul( t ) );
		const hz = dZ.mul( t );                  // how far into the room
		const onBack = step( tZ, min( tX, tY ) );
		const onFlat = step( tY, min( tX, tZ ) );
		const onCeil = onFlat.mul( step( 0.0, dY ) );
		const onFloor = onFlat.mul( step( dY, 0.0 ) );

		// ---- what that face is ------------------------------------------
		// three plausible paints, a boarded or a dark floor, and a ceiling
		// that is always the brightest thing in a room because it is what
		// the window's own light bounces off
		const wall = mix( mix( vec3( ...SR( '#cfc8bb' ) ), vec3( ...SR( '#bcbfc3' ) ),
			step( 0.42, rB ) ), vec3( ...SR( '#98a19b' ) ), step( 0.84, rB ) )
			.mul( vec3( ...cfg.wall ) );
		const floorC = mix( vec3( ...SR( '#6b5338' ) ), vec3( ...SR( '#3b3936' ) ),
			step( 0.68, rD ) ).mul( vec3( ...cfg.wall ) );
		const ceilC = vec3( ...SR( '#dad7d0' ) ).mul( vec3( ...cfg.wall ) );
		// a dark run of furniture along the foot of the back wall: an empty
		// room reads as a cardboard box however well it is lit
		const furn = smoothstep( float( 0.98 ), float( 0.62 ), hy.add(
			mx_noise_float( vec3( hx.mul( 1.6 ), rC.mul( 12.0 ), 0.0 ) ).mul( 0.26 ) ) )
			.mul( cfg.furniture );
		// corners hold shadow: only on the back wall, where it shows
		const nook = mix( float( 1.0 ), smoothstep( float( 0.0 ), float( 0.8 ),
			min( hx, float( cfg.w ).sub( hx ) ) ).mul( 0.45 ).add( 0.55 ), onBack );
		let surf = wall;
		surf = mix( surf, wall.mul( mix( float( 1.0 ), float( 0.30 ), furn ) ), onBack );
		surf = mix( surf, ceilC, onCeil );
		surf = mix( surf, floorC, onFloor );
		surf = surf.mul( nook );

		// ---- how much light reaches it ----------------------------------
		// A room is lit through its own window, so the light falls away with
		// depth, and the sky lighting it is the sky in front of the facade.
		// Both terms are radiances: a gain is the projected solid angle of
		// the opening over pi, which is the fraction of the sky a surface in
		// there actually sees - 7% for a back wall, 42% for a blind pressed
		// against the glass. That is the whole reason an unscreened window
		// photographs as a dark hole and a blind photographs as bright.
		const skyIn = skyAt( normalize( N.add( UP.mul( 0.5 ) ) ) );
		const fall = exp( hz.mul( -0.34 ) ).mul( 0.86 ).add( 0.14 );
		const sunN = saturate( dot( N, SUN ) );
		// the sun's cosine on whichever face the ray landed on: the back wall
		// faces the window, the floor faces up, the side walls across
		let cosF = abs( dot( SUN, right ) );
		cosF = mix( cosF, sunN, onBack );
		cosF = mix( cosF, saturate( SUN.y ), onFloor );
		cosF = mix( cosF, float( 0.0 ), onCeil );
		// and does the sun get in at all? Trace the hit point back out along
		// the sun direction and see whether it clears the opening. What
		// survives is a real patch of sunlight - 1.7 m deep across the floor
		// at this elevation, climbing the back wall as the sun drops.
		// Nothing else in a window says *interior* half as plainly.
		const sunT = hz.div( max( sunN, 0.05 ) );
		const ex = hx.add( dot( SUN, right ).mul( sunT ) );
		const ey = hy.add( SUN.y.mul( sunT ) );
		const seesSun = step( 0.02, sunN )
			.mul( smoothstep( float( 0.0 ), float( 0.40 ),
				min( ex, float( cfg.w ).sub( ex ) ) ) )
			.mul( smoothstep( float( 0.0 ), float( 0.30 ),
				min( ey.sub( cfg.sill ), float( cfg.head ).sub( ey ) ) ) );
		const lit = skyIn.mul( cfg.skyGain ).mul( fall )
			.add( SUNC.mul( cosF.mul( seesSun ).mul( SUN_E ) ) );
		let radiance = surf.mul( lit );

		// ---- blind or curtain, hanging just behind the glass ------------
		// Four states in the proportion a photograph of a residential block
		// shows them: most blinds right down, a few half up, some windows
		// curtained to the sides, a few bare. The plane is only 70 mm back,
		// so its parallax is slight - but its *edge* against the frame is
		// what the eye reads, and that edge now moves.
		const tB = float( cfg.blindZ ).div( dZ );
		const bx = x0.add( dX.mul( tB ) );
		const by = y0.add( dY.mul( tB ) );
		// `allDown`: every blind right down, no curtains, nothing bare - the
		// punched windows of the reference are one uniform white rectangle
		// each, the same height on every floor
		const isOpen = cfg.allDown ? float( 0.0 ) : step( 0.88, rA );
		const isCurtain = cfg.allDown ? float( 0.0 ) : step( 0.72, rA ).sub( isOpen );
		const drop = cfg.allDown ? float( 0.05 )
			: mix( float( 0.05 ), mix( float( 1.05 ), float( 2.05 ), rC ), step( 0.50, rA ) );
		const underHead = step( by, float( cfg.head ) );
		const fold = sin( bx.mul( 21.0 ).add( rC.mul( 40.0 ) ) ).mul( 0.5 ).add( 0.5 );
		const draw = mix( float( 0.22 ), float( 0.46 ), rC ).mul( cfg.w );
		const curtain = max(
			smoothstep( draw, draw.sub( 0.16 ), bx ),
			smoothstep( float( cfg.w ).sub( draw ), float( cfg.w ).sub( draw ).add( 0.16 ), bx )
		).mul( underHead );
		let cover = mix( step( drop, by ).mul( underHead ), curtain, isCurtain )
			.mul( oneMinus( isOpen ) ).mul( cfg.blinds );
		// weave and slats, faded out before they are smaller than a pixel
		const near = smoothstep( float( 70.0 ), float( 14.0 ), dist );
		// the slat coordinate is an absolute height, so without a per-room
		// offset every blind on a storey hangs with its slats in phase and
		// the facade reads as one printed sheet
		const weave = mix( float( 1.0 ), mix(
			fract( by.add( rA.mul( 0.051 ) ).mul( 1.0 / 0.052 ) ).mul( 0.26 ).add( 0.87 ),
			fold.mul( 0.30 ).add( 0.82 ), isCurtain ), near );
		// A blind is lit from the window side, so it is the brightest thing
		// in the opening - and when the sun is on the facade it glows. This
		// one surface decides whether a facade reads as lived in.
		// three cloths, and a transmittance that varies with them: a heavy
		// lined blind is a third darker than a cheap white roller, and that
		// spread between neighbouring flats is most of what tells the eye it
		// is looking at ninety separate households
		const blindTone = mix( mix( vec3( ...SR( '#e6e1d6' ) ), vec3( ...SR( '#c6c9cc' ) ),
			step( 0.40, rC ) ), vec3( ...SR( '#d6c7ad' ) ), step( 0.82, rC ) )
			.mul( float( 0.74 ).add( rB.mul( 0.46 ) ) );
		const blindRad = blindTone.mul( weave ).mul( skyIn.mul( cfg.blindSky )
			.add( SUNC.mul( sunN.mul( SUN_E ).mul( step( 0.02, sunN ) ) ) ) );
		radiance = mix( radiance, blindRad, cover );
		// above the head of a blind the ray is looking at the soffit of the
		// opening, which is the dark line along the top of a real window
		radiance = mix( radiance, skyIn.mul( 0.45 ),
			oneMinus( underHead ).mul( oneMinus( isOpen ) ).mul( cfg.blinds ) );

		// a few flats have a light on at midday: deep plan rooms do
		const lamp = max( step( 0.94, rD ), float( cfg.lampAll ) ).mul( cfg.lamp );
		radiance = radiance.add( mix( surf, blindTone, cover )
			.mul( vec3( ...SR( '#ffb968' ) ) )
			.mul( lamp.mul( mix( fall, float( 0.7 ), cover ) ) ) );

		return radiance;
	}

	/** Grime - the one genuinely diffuse part of a window, and so the only
	 *  part that belongs in the albedo. Dust gathers along the bottom of the
	 *  pane where the frame holds the water, and rain runs down from the head
	 *  in streaks. Kept out of the reflection, or it reads as fog. */
	function paneGrime( cfg ) {
		const P = positionWorld;
		const h = fract( P.y.sub( cfg.base ).div( cfg.pitch ) ).mul( cfg.pitch );
		const foot = smoothstep( float( cfg.sill + 0.45 ), float( cfg.sill ), h );
		const streak = mx_fractal_noise_float( P.mul( vec3( 5.5, 0.09, 5.5 ) ),
			3, 2.0, 0.5, 1.0 );
		const run = saturate( streak.mul( 1.5 ).add( 0.08 ) )
			.mul( smoothstep( float( cfg.head ), float( cfg.sill ), h ) );
		const film = saturate( mx_fractal_noise_float( P.mul( 0.5 ), 3, 2.0, 0.5, 1.0 )
			.mul( 0.7 ).add( 0.4 ) );
		// kept deliberately slight: a dirty window still has a diffuse albedo
		// of a few per cent, and at anything more the pane turns milky and
		// starts carrying more of the facade than what is behind it
		return saturate( foot.mul( 0.75 ).add( run.mul( 0.45 ) ).add( film.mul( 0.2 ) ) )
			.mul( cfg.grime );
	}

	/* One glazing material. `f0` is an *effective* normal incidence
	 * reflectance, not the 4.3% of a single air/glass interface: a sealed
	 * clear double glazed unit measures about 15% because the light meets
	 * four surfaces, and single laminated glass about 8% because it meets
	 * two. It is fed in through the ior rather than through
	 * specularIntensity, because specularIntensity scales F90 as well and
	 * would push the grazing reflectance past 1 - exactly where a facade
	 * spends most of its time. */
	function glazing( name, cfg ) {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = name;
		const P = positionWorld;
		const toEye = cameraPosition.sub( P );
		const dist = length( toEye );
		const V = toEye.div( dist );
		const ndv = saturate( dot( normalWorld, V ) );

		/* A sealed unit is never flat. The gas in it is closed at the factory
		 * and the pane bows in or out by a millimetre or two with the
		 * weather, which is why a glazed facade never mirrors the sky as one
		 * clean sheet. The right shape is a metre-scale swell, about a degree
		 * of it - large enough to vary the reflection pane by pane, far too
		 * large to alias at 100 m. */
		m.normalNode = bumpMap( mx_fractal_noise_float(
			P.mul( vec3( 1.3, 0.8, 1.3 ) ), 2, 2.0, 0.5, 1.0 ), float( cfg.bow ) );

		const r = Math.sqrt( cfg.f0 );
		m.iorNode = float( ( 1 + r ) / ( 1 - r ) );
		m.specularColorNode = vec3( 0.99, 1.0, 1.02 );   // faintly cool
		m.metalnessNode = float( 0.0 );
		m.envMapIntensity = cfg.env;

		/* The interior, weighted by 1-F: what is not reflected is what gets
		 * through. It is carried in emissive, not in the albedo, so the room
		 * is neither lit by the exterior sun nor darkened by the ambient
		 * occlusion of the reveal it sits in. It has its own light. */
		const F = float( cfg.f0 ).add( float( 1.0 - cfg.f0 )
			.mul( pow( oneMinus( ndv ), 5.0 ) ) );
		const room = cfg.room
			? interiorRoom( cfg, V, dist )
			: skyAt( normalize( normalWorld.add( UP.mul( 0.5 ) ) ) )
				.mul( vec3( ...cfg.wall ) ).mul( cfg.skyGain );
		// float glass is faintly green, and the deeper the ray cuts through
		// it the greener what comes back gets
		const tint = mix( vec3( 1.0, 1.0, 1.0 ), vec3( ...cfg.tint ), oneMinus( ndv ) );
		const grime = paneGrime( cfg );

		m.emissiveNode = room.mul( oneMinus( F ) ).mul( cfg.clarity ).mul( tint )
			.mul( oneMinus( grime.mul( 0.5 ) ) );
		m.colorNode = vec3( ...SR( '#8d8a82' ) ).mul( grime );
		// specular antialiasing: a pane is 3 px across at the far end of the
		// street, and a mirror that sharp sparkles under the temporal filter
		m.roughnessNode = clamp( float( cfg.rough ).add( grime.mul( 0.28 ) )
			.add( smoothstep( float( 60.0 ), float( 420.0 ), dist ).mul( 0.035 ) ),
		0.01, 1.0 );
		return m;
	}

	/* The room behind a flat. Floors every 3 m from the podium roof, party
	 * walls every quarter bay, 4.4 m deep - the real plan depth of these
	 * blocks less the corridor. */
	const FLAT = {
		room: true, base: 4.65, pitch: 3.00, w: 2.9325, depth: 4.40, ceil: 2.70,
		sill: 0.78, head: 2.66, blindZ: 0.07, blinds: 1.0, furniture: 1.0,
		wall: [ 1.0, 1.0, 1.0 ], skyGain: 0.075, blindSky: 0.42,
		lamp: 0.0, lampAll: 0.0,
		f0: 0.15, env: 0.72, rough: 0.022, bow: 0.020, grime: 0.12, clarity: 0.90,
		tint: [ 0.88, 0.99, 0.95 ],
	};
	M.glass_window = glazing( 'glass_window', FLAT );
	// the punched windows of both blocks: blinds down behind every one, as
	// the photograph shows them (the loggia doors keep the mixed states)
	M.glass_blind = glazing( 'glass_blind', { ...FLAT, allDown: true } );
	// the tenth of the flats that have the light on: the same glass, one more
	// lamp. In daylight it is a warm cast deep in the room, not a glow.
	M.glass_lit = glazing( 'glass_lit', { ...FLAT, lamp: 0.55, lampAll: 1.0 } );

	/* The stair and corridor slots in the west gable. No blinds, a landing
	 * 2.2 m back, and bare concrete - which is why the reference shows them
	 * as the one dark thing in a light wall. */
	/* With the gable rendered dark, the slots have to read as what the
	 * photograph shows: one uniform pane of sky-reflecting glass the full
	 * 2.4 m of the opening, no blind, no room - a stairwell is a dark box
	 * and all that comes back is the sky. room:false gives exactly that. */
	M.glass_slot = glazing( 'glass_slot', { ...FLAT,
		room: false, wall: [ 1.0, 1.0, 1.0 ], skyGain: 0.55, blinds: 0.0,
		sill: 0.18, head: 2.58, f0: 0.15, grime: 0.10, clarity: 1.0,
	} );

	/* The shopfront. Its own grid: one storey 4.65 m tall standing on the
	 * street, rooms two bays wide because a shop is not divided every 3 m,
	 * 6.5 m deep, and the light on all day. */
	M.glass_shop = glazing( 'glass_shop', { ...FLAT,
		base: 0.0, pitch: 4.65, w: 9.40, depth: 6.50, ceil: 4.05,
		sill: 0.55, head: 3.90, blinds: 0.0, furniture: 1.0,
		skyGain: 0.085, lamp: 0.85, lampAll: 1.0,
		grime: 0.10, rough: 0.018, bow: 0.014, env: 0.72,
	} );

	/* Car glass. Laminated single, so half the reflectance of a sealed unit,
	 * and no room behind it - a cabin is just a dark box, and at this size
	 * the only thing that reads is the sky bent across the screen. */
	M.car_glass = glazing( 'car_glass', { ...FLAT,
		room: false, wall: [ 0.09, 0.095, 0.10 ], skyGain: 0.55,
		f0: 0.083, rough: 0.014, bow: 0.012, grime: 0.06, clarity: 1.0,
		sill: 0.0, head: 1.4, base: 0.0, pitch: 1.6,
	} );

	M.blind = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'blind';
		const h = panelHash( positionWorld.mul( 1.7 ) );
		const base = vec3( ...SR( '#ddd9d0' ) ).mul( float( 0.86 ).add( h.mul( 0.28 ) ) );
		m.colorNode = base;
		m.roughnessNode = float( 0.93 );
		m.emissiveNode = base.mul( float( 0.42 ).add( h.mul( 0.3 ) ) );
		return m;
	} )();


	M.shop_interior = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'shop_interior';
		const n = grain( 1.4, 4 );
		m.colorNode = vec3( ...SR( '#6d5f4b' ) ).mul( float( 1.0 ).add( n.mul( 0.4 ) ) );
		m.emissiveNode = vec3( ...SR( '#ffd9a4' ) ).mul( float( 0.55 ).add( n.mul( 0.35 ) ) );
		m.roughnessNode = float( 0.8 );
		return m;
	} )();

	M.neon_orange = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'neon_orange';
		m.colorNode = vec3( ...SR( '#ff5a16' ) );
		m.emissiveNode = vec3( ...SR( '#ff5f1d' ) ).mul( 7.5 );
		m.roughnessNode = float( 0.45 );
		return m;
	} )();

	// ---------------------------------------------------------- metals
	function metalMat( name, hex, rough, metal ) {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = name;
		const n = grain( 9.0, 3 );
		m.colorNode = vec3( ...SR( hex ) ).mul( float( 1.0 ).add( n.mul( 0.12 ) ) );
		m.roughnessNode = clamp( float( rough ).add( n.mul( 0.08 ) ), 0.02, 1.0 );
		m.metalnessNode = float( metal );
		return m;
	}
	M.metal_dark = metalMat( 'metal_dark', '#43444a', 0.34, 0.9 );
	M.reveal_dark = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'reveal_dark';
		m.colorNode = vec3( ...SR( '#15141a' ) );
		m.roughnessNode = float( 0.6 );
		m.metalnessNode = float( 0.15 );
		return m;
	} )();
	M.frame_bronze = metalMat( 'frame_bronze', '#2e2a26', 0.40, 0.62 );
	// the gable slot frames: pale painted metal, as the photograph shows them
	M.frame_light = metalMat( 'frame_light', '#d9d6ce', 0.48, 0.30 );
	M.pole_metal = metalMat( 'pole_metal', '#26282c', 0.44, 0.65 );
	M.sign_metal = metalMat( 'sign_metal', '#3d3d40', 0.33, 0.72 );
	M.chrome = metalMat( 'chrome', '#cdd0d4', 0.14, 1.0 );

	// ------------------------------------------------ balcony balustrade
	/* PolyHaven "worn shutter" - a ribbed, weathered roller shutter. Stood on
	 * end so its ribs run vertically it is exactly a painted metal balustrade.
	 * The rib pitch is deliberately left incommensurate with the 89 mm picket
	 * pitch, so no two pickets take their tone from the same part of a rib and
	 * the run of balusters gets the uneven glint a real one has.
	 * The scan is as dark as the asphalt one and is handled the same way: its
	 * mean is divided out and the result retinted. The hue needs no correcting
	 * - the scan's linear channel ratios (1 : 0.84 : 0.67) are already exactly
	 * those of the railings in the reference photograph. */
	M.rail_balcony = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		const MEAN = 0.049;                       // mean linear luminance of the scan
		const TINT = vec3( ...SR( '#a2998b' ) );
		m.name = 'rail_balcony';
		// u runs along the ribs  -> world height, so stains run down a picket
		// v runs across the ribs -> horizontal, so the ribbing stands upright
		const horiz = positionWorld.x.add( positionWorld.z );
		const uvA = vec2( positionWorld.y.mul( 1 / 2.20 ), horiz.mul( 1 / 1.55 ) );
		const uvB = vec2( positionWorld.y.mul( 1 / 6.30 ),
			horiz.mul( 1 / 4.37 ) ).add( vec2( 0.31, 0.67 ) );
		const blend = saturate( grain( 0.14, 3 ).mul( 1.6 ).add( 0.5 ) );
		const n = grain( 9.0, 3 );

		if ( maps.railDiff ) {
			const sA = texture( maps.railDiff, uvA ).rgb;
			const sB = texture( maps.railDiff, uvB ).rgb;
			m.colorNode = TINT.mul( clamp( mix( sA, sB, blend ).div( MEAN ), 0.45, 1.9 ) );
		} else {
			m.colorNode = TINT.mul( float( 1.0 ).add( n.mul( 0.12 ) ) );
		}

		// The scan's roughness map is all but flat (0.67-0.76), so its level is
		// taken as a constant and the variation comes off the height instead:
		// paint wears thin on the crests of the ribs and the metal shines
		// through, while the valleys hold dirt and stay matt.
		if ( maps.railDisp ) {
			const hA = texture( maps.railDisp, uvA ).r;
			const hB = texture( maps.railDisp, uvB ).r;
			const h = mix( hA, hB, blend );
			m.roughnessNode = clamp( float( 0.73 ).sub( h.sub( 0.6 ).mul( 0.45 ) ), 0.22, 0.95 );
			m.normalNode = bumpMap( h, float( 0.14 ) );
		} else {
			m.roughnessNode = clamp( float( 0.73 ).add( n.mul( 0.08 ) ), 0.22, 0.95 );
			m.normalNode = bumpMap( n, float( 0.10 ) );
		}
		// painted steel, not bare: kept dielectric so the warm colour survives.
		// At 0.35 the sky reflection washed the railings neutral and lost the
		// warm cast they have in the photograph.
		m.metalnessNode = float( 0.18 );
		return m;
	} )();
	M.tire = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'tire';
		m.colorNode = vec3( ...SR( '#141416' ) );
		m.roughnessNode = float( 0.82 );
		m.metalnessNode = float( 0.0 );
		return m;
	} )();

	// ---------------------------------------------------------- car paint
	const carHex = [ '#1b1e23', '#8f949b', '#2f3d54', '#707174', '#babdc1',
		'#322922', '#1f4a33', '#5c6066', '#7c7d81', '#282c31' ];
	carHex.forEach( ( hex, i ) => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'car_paint_' + i;
		m.colorNode = vec3( ...SR( hex ) );
		m.roughnessNode = float( 0.26 );
		m.metalnessNode = float( 0.62 );
		m.clearcoatNode = float( 1.0 );
		m.clearcoatRoughnessNode = float( 0.045 );
		M[ 'car_paint_' + i ] = m;
	} );
	M.bus_green = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'bus_green';
		m.colorNode = vec3( ...SR( '#78c242' ) );
		m.roughnessNode = float( 0.34 );
		m.metalnessNode = float( 0.12 );
		m.clearcoatNode = float( 0.7 );
		m.clearcoatRoughnessNode = float( 0.09 );
		return m;
	} )();

	// ---------------------------------------------------------- planting
	/* Foliage. Three things carry it, and none of them is the green.
	 *
	 * The per-leaf tint comes in as a vertex colour baked in Blender - sun
	 * leaves lighter and yellower, shade leaves darker and bluer. A noise in
	 * world space cannot do this: it varies over centimetres, so neighbouring
	 * leaves come out the same shade and the canopy reads as one painted
	 * surface.
	 *
	 * The underside is a different material from the top. It is paler, greyer
	 * and matt where the upper face has a waxy cuticle, and because half the
	 * leaves in any canopy show you their backs, that difference is most of
	 * what stops foliage reading as green card. `frontFacing` is true on the
	 * side the blade is wound toward, which the generator points at the sun.
	 *
	 * And they glow when the sun is behind them. */
	function leafMat( name, hex ) {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = name;
		m.side = THREE.DoubleSide;
		const n = grain( 0.25, 3 );
		const top = vec3( ...SR( hex ) ).mul( vertexColor().rgb )
			.mul( float( 1.0 ).add( n.mul( 0.16 ) ) );
		const under = mix( top, vec3( ...SR( '#93a078' ) ), 0.38 ).mul( 1.05 );
		m.colorNode = select( frontFacing, top, under );
		m.roughnessNode = select( frontFacing,
			float( 0.52 ).add( n.mul( 0.16 ) ), float( 0.88 ) );
		const back = saturate( dot( normalWorld, SUN ).negate() );
		m.emissiveNode = top.mul( SUNC ).mul( pow( back, float( 3.0 ) ) ).mul( 0.95 );
		return m;
	}
	M.foliage = leafMat( 'foliage', '#4b6128' );
	M.foliage_b = leafMat( 'foliage_b', '#577331' );

	M.bark = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'bark';
		const n = grain( 7.0, 4 );
		const v = grain( 36.0, 2 );
		m.colorNode = vec3( ...SR( '#4e453b' ) ).mul( clamp( float( 1.0 ).add( n.mul( 0.33 ) ), 0.6, 1.5 ) );
		m.roughnessNode = float( 0.90 );
		m.normalNode = bumpMap( n.mul( 0.6 ).add( v.mul( 0.4 ) ), float( 0.55 ) );
		return m;
	} )();

	M.soil = renderPlaster( 'soil', '#3f372d', 0.95, 4.0, 0.14, 0.3 );
	M.canopy_fabric = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'canopy_fabric';
		m.side = THREE.DoubleSide;
		m.colorNode = vec3( ...SR( '#f2f1ec' ) );
		m.roughnessNode = float( 0.74 );
		m.metalnessNode = float( 0.0 );
		m.sheenNode = float( 0.35 );
		m.envMapIntensity = 0.55;
		return m;
	} )();
	M.person = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'person';
		const h = panelHash( positionWorld.mul( 0.4 ) );
		m.colorNode = mix( vec3( ...SR( '#262429' ) ), vec3( ...SR( '#6a6258' ) ), h );
		m.roughnessNode = float( 0.85 );
		return m;
	} )();


	// ---------------------------------------------------------- the show flat
	/* Everything inside the flat is keyed to the flat's own axes, not the
	 * world's: parquet and tiles have to run with the walls, and the walls
	 * stand at the block's bearing. `opts.flat` carries the frame the build
	 * wrote out (scene_meta.json); without it the pattern falls back to the
	 * world axes. */
	const FR = opts.flat || null;
	const F_EX = vec3( ...( FR ? FR.ex : [ 1, 0, 0 ] ) );
	const F_EY = vec3( ...( FR ? FR.ey : [ 0, 0, -1 ] ) );
	const F_O = vec3( ...( FR ? FR.origin : [ 0, 0, 0 ] ) );
	const flatUV = () => {
		const p = positionWorld.sub( F_O );
		return vec2( dot( p, F_EX ), dot( p, F_EY ) );
	};
	const hash2 = ( a, b, seed ) => fract( sin(
		a.mul( 127.1 ).add( b.mul( 311.7 ) ).add( seed ) ).mul( 43758.5453 ) );
	const fmod = ( a, m ) => a.sub( a.div( m ).floor().mul( m ) );

	/* Herringbone parquet, scanned: the PolyHaven "herringbone parquet" set
	 * (CC0, a 3.4 m tile) out of `herringbone_parquet_4k.blend`, down-sampled
	 * into web/tex - the EXRs through the pixel buffer, so the normal map
	 * stays linear. It is laid on the flat's own axes, so the chevrons run
	 * into the depth of the rooms and the boards sit square with the walls,
	 * and it is continuous from room to room the way a real floor is.
	 *
	 * With no maps loaded the older procedural herringbone still draws:
	 * planks of n widths by one in the classic zig-zag at 45 degrees to the
	 * walls, where the cell (i, j) of a grid one plank wide belongs to a
	 * horizontal plank when (i + j) mod 2n < n and to a vertical one
	 * otherwise, so every board gets an identity, its own tint and grain. */
	M.int_parquet = ( () => {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = 'int_parquet';
		const uv = flatUV();
		m.metalnessNode = float( 0.0 );

		if ( maps.parquetDiff ) {
			const TILE = 3.4;                        // the scan's real-world size
			const q = uv.mul( 1 / TILE );
			/* The tile repeats about three times across the flat, which the
			 * eye picks up on a plain floor, so a slow noise drifts the tone
			 * between repeats and the grid stops reading. */
			const drift = mx_fractal_noise_float(
				vec3( uv.x.mul( 0.11 ), uv.y.mul( 0.11 ), 3.7 ), 3, 2.0, 0.5, 1.0 );
			m.colorNode = texture( maps.parquetDiff, q ).rgb
				.mul( clamp( float( 1.0 ).add( drift.mul( 0.13 ) ), 0.82, 1.18 ) );
			// the scan is a showroom lacquer (0.03-0.20); lifted a little, or
			// the whole flat mirrors in the floor
			m.roughnessNode = maps.parquetRough
				? clamp( texture( maps.parquetRough, q ).r.add( 0.08 ).add( drift.mul( 0.03 ) ), 0.09, 0.8 )
				: float( 0.24 );
			if ( maps.parquetNor ) {
				/* Tangent frame straight off the flat's own: the floor is one
				 * horizontal slab, so u runs along ex and v along ey (the scan
				 * is OpenGL-handed, green = +v) and the merged mesh needs
				 * neither UVs nor tangents. */
				const n = texture( maps.parquetNor, q ).xyz.mul( 2.0 ).sub( 1.0 );
				const world = normalize( F_EX.mul( n.x ).add( F_EY.mul( n.y ) )
					.add( vec3( 0, 1, 0 ).mul( n.z ) ) );
				m.normalNode = normalize( cameraViewMatrix.transformDirection( world ) );
			}
			return m;
		}

		const W = 0.072, N = 5;
		const s = Math.SQRT1_2;
		const x = uv.x.mul( s ).sub( uv.y.mul( s ) ).div( W );
		const y = uv.x.mul( s ).add( uv.y.mul( s ) ).div( W );
		const i = floor( x ), j = floor( y );
		const k = fmod( i.add( j ), float( 2 * N ) );
		const isH = step( k, float( N - 0.5 ) );
		const oxH = i.sub( k ), oyH = j;
		const oxV = i, oyV = j.sub( k.sub( N ) );
		const ox = mix( oxV, oxH, isH ), oy = mix( oyV, oyH, isH );
		const sL = mix( y.sub( oyV ).div( N ), x.sub( oxH ).div( N ), isH );   // along, 0..1
		const tL = mix( x.sub( oxV ), y.sub( oyH ), isH );                     // across, 0..1
		const edge = min( min( sL, oneMinus( sL ) ).mul( N ), min( tL, oneMinus( tL ) ) ).mul( W );
		const gap = smoothstep( 0.0, 0.0035, edge );
		const id = hash2( ox, oy, isH.mul( 7.3 ) );
		const id2 = hash2( ox, oy, isH.mul( 3.1 ).add( 51.0 ) );
		const g = mx_fractal_noise_float( vec3(
			sL.mul( N * W * 5.0 ).add( id.mul( 40.0 ) ), tL.mul( W * 90.0 ), id2.mul( 10.0 ) ),
		3, 2.0, 0.5, 1.0 );
		const tone = float( 0.80 ).add( id.mul( 0.40 ) ).add( g.mul( 0.14 ) );
		const warm = mix( vec3( ...SR( '#a97c4c' ) ), vec3( ...SR( '#c9a070' ) ), id2 );
		m.colorNode = warm.mul( tone ).mul( mix( float( 0.55 ), float( 1.0 ), gap ) );
		m.roughnessNode = clamp( float( 0.42 ).add( g.mul( 0.12 ) ).add( oneMinus( gap ).mul( 0.3 ) ), 0.2, 1.0 );
		m.normalNode = bumpMap( g.mul( 0.5 ).add( gap ), float( 0.08 ) );
		return m;
	} )();

	/** Ceramic tiles with a grout line. Floors tile on the plan, walls on
	 *  (along the wall, height), chosen by the surface normal. */
	function tiles( name, hex, tw, th, rough, groutHex ) {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = name;
		const uv = flatUV();
		const h = positionWorld.y;
		const nx = abs( dot( normalWorld, F_EX ) );
		const ny = abs( dot( normalWorld, F_EY ) );
		const nz = abs( normalWorld.y );
		const q = select( nz.greaterThan( 0.5 ), uv,
			select( ny.greaterThan( nx ), vec2( uv.x, h ), vec2( uv.y, h ) ) );
		const c = vec2( q.x.div( tw ), q.y.div( th ) );
		const ci = floor( c ), f = fract( c );
		const e = min( min( f.x, oneMinus( f.x ) ).mul( tw ), min( f.y, oneMinus( f.y ) ).mul( th ) );
		const grout = smoothstep( 0.0, 0.0025, e );
		const id = hash2( ci.x, ci.y, 0.0 );
		const n = grain( 9.0, 2 );
		const base = vec3( ...SR( hex ) ).mul( float( 0.93 ).add( id.mul( 0.14 ) ) ).mul( float( 1.0 ).add( n.mul( 0.05 ) ) );
		m.colorNode = mix( vec3( ...SR( groutHex ) ), base, grout );
		m.roughnessNode = mix( float( 0.9 ), float( rough ).add( n.mul( 0.04 ) ), grout );
		m.normalNode = bumpMap( grout, float( 0.12 ) );
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.35 ).mul( grout );
		m.clearcoatRoughnessNode = float( 0.12 );
		return m;
	}
	M.int_tile_grey = tiles( 'int_tile_grey', '#8e9091', 0.30, 0.60, 0.26, '#6e6f6f' );
	M.int_tile_white = tiles( 'int_tile_white', '#e6e4df', 0.30, 0.30, 0.24, '#b9b7b2' );

	M.int_marble = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_marble';
		const p = positionWorld.mul( 1.6 );
		const n1 = mx_fractal_noise_float( p, 4, 2.0, 0.5, 1.0 );
		const n2 = mx_fractal_noise_float( p.mul( 2.3 ).add( 7.0 ), 3, 2.0, 0.5, 1.0 );
		const vein = pow( oneMinus( abs( sin( n1.mul( 6.0 ).add( n2.mul( 2.0 ) ) ) ) ), 8.0 );
		const vein2 = pow( oneMinus( abs( sin( n2.mul( 9.0 ).add( 1.7 ) ) ) ), 14.0 );
		m.colorNode = mix( vec3( ...SR( '#ebe8e3' ) ), vec3( ...SR( '#6f7075' ) ),
			saturate( vein.mul( 0.75 ).add( vein2.mul( 0.45 ) ) ) );
		m.roughnessNode = float( 0.12 );
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.6 );
		m.clearcoatRoughnessNode = float( 0.06 );
		return m;
	} )();

	/* The rug in the TV room: PolyHaven "fabric pattern 05". Laid in the
	 * flat's frame so the weave runs with the room, at its real pile scale
	 * rather than stretched to the rug, and lifted into a short pile by the
	 * normal map. */
	M.int_rug = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_rug';
		const p = positionWorld.sub( F_O );
		const q = vec2( dot( p, F_EX ), dot( p, F_EY ) ).div( 1.30 );
		if ( maps.rugDiff ) {
			m.colorNode = texture( maps.rugDiff, q ).rgb.mul( 0.98 );
			m.roughnessNode = maps.rugRough
				? clamp( texture( maps.rugRough, q ).r.mul( 0.5 ).add( 0.5 ), 0.5, 1.0 )
				: float( 0.95 );
			if ( maps.rugNor ) {
				const nn = texture( maps.rugNor, q ).xyz.mul( 2.0 ).sub( 1.0 );
				m.normalNode = normalize( cameraViewMatrix.transformDirection(
					normalize( normalWorld.add( vec3( nn.x, nn.y, 0.0 ).mul( 1.1 ) ) ) ) );
			}
		} else {
			const pile = grain( 60.0, 2 );
			m.colorNode = vec3( ...SR( '#9a9ea5' ) ).mul( float( 1.0 ).add( pile.mul( 0.12 ) ) );
			m.roughnessNode = float( 0.95 );
		}
		m.metalnessNode = float( 0.0 );
		m.sheenNode = float( 0.5 );
		m.sheenRoughnessNode = float( 0.8 );
		return m;
	} )();

	function cloth( name, hex, rough = 0.9, sheen = 0.5, double = false ) {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = name;
		const n = grain( 40.0, 2 );
		m.colorNode = vec3( ...SR( hex ) ).mul( float( 1.0 ).add( n.mul( 0.10 ) ) );
		m.roughnessNode = float( rough );
		m.metalnessNode = float( 0.0 );
		m.sheenNode = float( sheen );
		m.sheenRoughnessNode = float( 0.6 );
		m.normalNode = bumpMap( n, float( 0.06 ) );
		if ( double ) m.side = THREE.DoubleSide;
		return m;
	}
	M.int_fabric_teal = cloth( 'int_fabric_teal', '#3c8a84' );
	M.int_fabric_bluegrey = cloth( 'int_fabric_bluegrey', '#8294a8' );
	M.int_fabric_white = cloth( 'int_fabric_white', '#eeeae2', 0.85, 0.4 );
	M.int_fabric_orange = cloth( 'int_fabric_orange', '#d6622a' );
	M.int_fabric_sofa = cloth( 'int_fabric_sofa', '#7b7f86', 0.95, 0.35 );
	M.int_fabric_dark = cloth( 'int_fabric_dark', '#3d4148', 0.95, 0.3 );
	/* Curtains and the built-in joinery are the two surfaces you stand
	 * closest to in the flat, so both carry a scanned map rather than noise.
	 * The cloth is PolyHaven "leather white", which at curtain scale reads as
	 * a heavy woven linen; the joinery is "teak veneer". Neither mesh has UVs
	 * - both are built procedurally - so both are projected in the flat's own
	 * frame: the cloth by (distance along the run, height), which is how a
	 * hanging fabric is actually woven, and the veneer with its grain running
	 * up the door. */
	const flatRun = () => {
		const p = positionWorld.sub( F_O );
		return dot( p, F_EX ).add( dot( p, F_EY ) );
	};
	M.int_curtain = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_curtain';
		m.side = THREE.DoubleSide;
		const q = vec2( flatRun().mul( 1 / 0.90 ), positionWorld.y.mul( 1 / 1.35 ) );
		const n = grain( 30.0, 3 );
		if ( maps.leatherDiff ) {
			const d = texture( maps.leatherDiff, q ).rgb;
			// the scan is a warm off-white; cooled a little toward the render's grey
			m.colorNode = d.mul( vec3( 0.92, 0.95, 1.0 ) ).mul( 0.96 );
			m.opacityNode = clamp( float( 0.86 ).add( lum( d ).sub( 0.78 ).mul( 0.4 ) ), 0.78, 0.97 );
		} else {
			m.colorNode = vec3( ...SR( '#ccd2da' ) ).mul( float( 1.0 ).add( n.mul( 0.14 ) ) );
			m.opacityNode = float( 0.90 );
		}
		m.transparent = true;
		m.roughnessNode = maps.leatherRough
			? clamp( texture( maps.leatherRough, q ).r.mul( 0.5 ).add( 0.55 ), 0.4, 1.0 )
			: float( 0.86 );
		if ( maps.leatherNor ) {
			const nn = texture( maps.leatherNor, q ).xyz.mul( 2.0 ).sub( 1.0 );
			m.normalNode = normalize( cameraViewMatrix.transformDirection(
				normalize( normalWorld.add( vec3( nn.x, nn.y, 0.0 ).mul( 0.35 ) ) ) ) );
		}
		m.metalnessNode = float( 0.0 );
		m.sheenNode = float( 0.9 );
		m.sheenRoughnessNode = float( 0.55 );
		m.sheenColorNode = vec3( 1.0, 0.99, 0.96 );
		return m;
	} )();

	/* The door leaves: PolyHaven "white planks clean", a painted boarded
	 * panel. The boards must run UP a door, never across it, so the vertical
	 * faces are mapped (horizontal, height) and the tile is set to the real
	 * board pitch rather than scaled to the leaf. */
	/* The bathroom. Walls take a scanned modern white wall tile (ambientCG
	 * Tiles133A), the floor a scanned marble tile (Tiles074); both are mapped
	 * in the flat's frame - vertical faces by (along the wall, height) so the
	 * courses stay level, the floor by the plan. */
	function scanTile( name, m3, tile, tint, rough ) {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = name;
		const p = positionWorld.sub( F_O );
		const u = dot( p, F_EX ), v = dot( p, F_EY ), hh = positionWorld.y;
		const nx = abs( dot( normalWorld, F_EX ) ), ny = abs( dot( normalWorld, F_EY ) );
		const nz = abs( normalWorld.y );
		const q = select( nz.greaterThan( 0.6 ), vec2( u, v ),
			select( nx.greaterThan( ny ), vec2( v, hh ), vec2( u, hh ) ) ).div( tile );
		if ( m3.d ) {
			m.colorNode = texture( m3.d, q ).rgb.mul( vec3( ...tint ) );
			m.roughnessNode = m3.r
				? clamp( texture( m3.r, q ).r.mul( 0.8 ).add( rough ), 0.04, 0.95 )
				: float( rough + 0.2 );
			if ( m3.n ) {
				const nn = texture( m3.n, q ).xyz.mul( 2.0 ).sub( 1.0 );
				m.normalNode = normalize( cameraViewMatrix.transformDirection(
					normalize( normalWorld.add( vec3( nn.x, nn.y, 0.0 ).mul( 0.7 ) ) ) ) );
			}
		} else {
			m.colorNode = vec3( ...tint );
			m.roughnessNode = float( rough + 0.2 );
		}
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.6 );
		m.clearcoatRoughnessNode = float( 0.08 );
		return m;
	}
	M.int_tile_wall = scanTile( 'int_tile_wall',
		{ d: maps.btileDiff, r: maps.btileRough, n: maps.btileNor }, 0.62, [ 1.0, 1.0, 1.0 ], 0.06 );
	M.int_tile_floor = scanTile( 'int_tile_floor',
		{ d: maps.bfloorDiff, r: maps.bfloorRough, n: maps.bfloorNor }, 0.80, [ 0.95, 0.96, 0.98 ], 0.08 );

	/* The dining chairs. They are downloaded models and do carry UVs, so this
	 * one is mapped off the model's own coordinates. The sheet behind it is a
	 * bright tan-orange - the render's chairs are black, so only its grain is
	 * kept and it is laid over charcoal. */
	M.int_leather_red = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_leather_red';
		const q = uv().mul( 2.4 );
		if ( maps.redDiff ) {
			const lr = texture( maps.redDiff, q ).rgb;
			const lum = lr.r.mul( 0.30 ).add( lr.g.mul( 0.59 ) ).add( lr.b.mul( 0.11 ) );
			m.colorNode = vec3( ...SR( '#202227' ) ).mul( lum.mul( 1.5 ).add( 0.55 ) );
			m.roughnessNode = maps.redRough
				? clamp( texture( maps.redRough, q ).r.mul( 0.7 ).add( 0.24 ), 0.2, 0.95 )
				: float( 0.5 );
			if ( maps.redNor ) {
				const nn = texture( maps.redNor, q ).xyz.mul( 2.0 ).sub( 1.0 );
				m.normalNode = normalize( cameraViewMatrix.transformDirection(
					normalize( normalWorld.add( vec3( nn.x, nn.y, 0.0 ).mul( 0.8 ) ) ) ) );
			}
		} else {
			m.colorNode = vec3( ...SR( '#7e1f1c' ) );
			m.roughnessNode = float( 0.5 );
		}
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.25 );
		m.clearcoatRoughnessNode = float( 0.35 );
		m.sheenNode = float( 0.2 );
		return m;
	} )();
	// the downloaded dining chair wears it
	M.dining_chair_02 = M.int_leather_red;

	/* The downloaded armchair ships as black leather on a pale wood frame;
	 * the render's is a charcoal upholstered lounge chair, so it is re-covered
	 * here. The model's own geometry is what matters, not its colour. */
	/* The lounge chair in front of the TV. The model ships as black leather
	 * on a pale wood frame and carries TWO materials, so both are re-covered:
	 * charcoal upholstery on the cushions, a near-black frame under them. */
	M.modern_arm_chair_01_pillow = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'modern_arm_chair_01_pillow';
		const n = grain( 42.0, 3 );
		m.colorNode = vec3( ...SR( '#343944' ) ).mul( float( 1.0 ).add( n.mul( 0.10 ) ) );
		m.roughnessNode = clamp( float( 0.86 ).add( n.mul( 0.08 ) ), 0.5, 1.0 );
		m.metalnessNode = float( 0.0 );
		m.sheenNode = float( 0.45 );
		m.sheenRoughnessNode = float( 0.65 );
		m.normalNode = bumpMap( n, float( 0.06 ) );
		return m;
	} )();
	M.modern_arm_chair_01_legs = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'modern_arm_chair_01_legs';
		const n = grain( 18.0, 3 );
		m.colorNode = vec3( ...SR( '#23262c' ) ).mul( float( 1.0 ).add( n.mul( 0.10 ) ) );
		m.roughnessNode = float( 0.45 );
		m.metalnessNode = float( 0.15 );
		return m;
	} )();
	M.modern_arm_chair_01 = M.modern_arm_chair_01_pillow;

	// the dining table: white marble top, as the render has it
	M.dining_table = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'dining_table';
		const p2 = positionWorld.mul( 1.7 );
		const n1 = mx_fractal_noise_float( p2, 4, 2.0, 0.5, 1.0 );
		const n2 = mx_fractal_noise_float( p2.mul( 2.2 ).add( 5.0 ), 3, 2.0, 0.5, 1.0 );
		const vein = pow( oneMinus( abs( sin( n1.mul( 6.0 ).add( n2.mul( 2.0 ) ) ) ) ), 9.0 );
		m.colorNode = mix( vec3( ...SR( '#edeae5' ) ), vec3( ...SR( '#8d9095' ) ), saturate( vein.mul( 0.8 ) ) );
		m.roughnessNode = float( 0.16 );
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.6 );
		m.clearcoatRoughnessNode = float( 0.08 );
		return m;
	} )();

	// the little round table: a pale stone top, as in the render
	M.coffee_table_round_01 = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'coffee_table_round_01';
		const n = grain( 9.0, 3 );
		m.colorNode = vec3( ...SR( '#e4e2dd' ) ).mul( float( 1.0 ).add( n.mul( 0.07 ) ) );
		m.roughnessNode = float( 0.26 );
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.5 );
		m.clearcoatRoughnessNode = float( 0.12 );
		return m;
	} )();

	// the dark top of the coffee table built to match the render
	M.int_coffee_top = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_coffee_top';
		const n = grain( 14.0, 3 );
		m.colorNode = vec3( ...SR( '#2b3139' ) ).mul( float( 1.0 ).add( n.mul( 0.06 ) ) );
		m.roughnessNode = float( 0.22 );
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.7 );
		m.clearcoatRoughnessNode = float( 0.09 );
		return m;
	} )();

	M.int_door_leaf = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_door_leaf';
		const TILE = 1.05;
		const p = positionWorld.sub( F_O );
		const u = dot( p, F_EX ), v = dot( p, F_EY ), hh = positionWorld.y;
		const nx = abs( dot( normalWorld, F_EX ) ), ny = abs( dot( normalWorld, F_EY ) );
		const nz = abs( normalWorld.y );
		const q = select( nz.greaterThan( 0.6 ), vec2( u, v ),
			select( nx.greaterThan( ny ), vec2( v, hh ), vec2( u, hh ) ) ).div( TILE );
		if ( maps.planksDiff ) {
			m.colorNode = texture( maps.planksDiff, q ).rgb.mul( 1.02 );
			m.roughnessNode = maps.planksRough
				? clamp( texture( maps.planksRough, q ).r.mul( 0.75 ).add( 0.18 ), 0.16, 0.92 )
				: float( 0.38 );
			if ( maps.planksNor ) {
				const nn = texture( maps.planksNor, q ).xyz.mul( 2.0 ).sub( 1.0 );
				m.normalNode = normalize( cameraViewMatrix.transformDirection(
					normalize( normalWorld.add( vec3( nn.x, nn.y, 0.0 ).mul( 0.6 ) ) ) ) );
			}
		} else {
			m.colorNode = vec3( ...SR( '#ece9e3' ) );
			m.roughnessNode = float( 0.35 );
		}
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.45 );
		m.clearcoatRoughnessNode = float( 0.16 );
		return m;
	} )();

	M.int_wood_teak = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_wood_teak';
		const TILE = 1.15;
		const p = positionWorld.sub( F_O );
		const u = dot( p, F_EX ), v = dot( p, F_EY ), h = positionWorld.y;
		const nx = abs( dot( normalWorld, F_EX ) ), ny = abs( dot( normalWorld, F_EY ) );
		const nz = abs( normalWorld.y );
		const q = select( nz.greaterThan( 0.6 ), vec2( u, v ),
			select( nx.greaterThan( ny ), vec2( v, h ), vec2( u, h ) ) ).div( TILE );
		if ( maps.teakDiff ) {
			m.colorNode = texture( maps.teakDiff, q ).rgb.mul( 1.04 );
			m.roughnessNode = maps.teakRough
				? clamp( texture( maps.teakRough, q ).r.mul( 0.8 ).add( 0.16 ), 0.14, 0.9 )
				: float( 0.42 );
			if ( maps.teakNor ) {
				const nn = texture( maps.teakNor, q ).xyz.mul( 2.0 ).sub( 1.0 );
				m.normalNode = normalize( cameraViewMatrix.transformDirection(
					normalize( normalWorld.add( vec3( nn.x, nn.y, 0.0 ).mul( 0.5 ) ) ) ) );
			}
		} else {
			const g = mx_fractal_noise_float( positionWorld.mul( vec3( 3.0, 40.0, 3.0 ) ), 3, 2.0, 0.5, 1.0 );
			m.colorNode = vec3( ...SR( '#8a5a32' ) ).mul( float( 1.0 ).add( g.mul( 0.2 ) ) );
			m.roughnessNode = float( 0.45 );
		}
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( 0.35 );
		m.clearcoatRoughnessNode = float( 0.22 );
		return m;
	} )();
	M.int_lamp_shade = ( () => {
		const m = cloth( 'int_lamp_shade', '#f1e8d6', 0.7, 0.3, true );
		m.emissiveNode = vec3( ...SR( '#ffd9a6' ) ).mul( 0.25 );
		return m;
	} )();

	function simple( name, hex, rough, metal = 0.0, vary = 0.05 ) {
		const m = new THREE.MeshStandardNodeMaterial();
		m.name = name;
		const n = grain( 12.0, 2 );
		m.colorNode = vec3( ...SR( hex ) ).mul( float( 1.0 ).add( n.mul( vary ) ) );
		m.roughnessNode = clamp( float( rough ).add( n.mul( 0.04 ) ), 0.02, 1.0 );
		m.metalnessNode = float( metal );
		return m;
	}
	function gloss( name, hex, rough, coat = 0.8 ) {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = name;
		m.colorNode = vec3( ...SR( hex ) );
		m.roughnessNode = float( rough );
		m.metalnessNode = float( 0.0 );
		m.clearcoatNode = float( coat );
		m.clearcoatRoughnessNode = float( 0.08 );
		return m;
	}
	M.int_wall = ( () => {
		const m = simple( 'int_wall', '#d9d5cc', 0.92, 0.0, 0.04 );
		m.normalNode = bumpMap( grain( 25.0, 2 ), float( 0.04 ) );
		return m;
	} )();
	/* The same wall, under another name, for the linings and cheeks of the
	 * loggias. They are a metre and a half into the flat - too deep for the
	 * shallow cut, which has to stay a finger thick or it eats the
	 * partitions - so they need a material of their own to be taken away
	 * with the balconies when a storey opens. Nothing about it differs. */
	M.int_wall_loggia = ( () => {
		const m = simple( 'int_wall_loggia', '#d9d5cc', 0.92, 0.0, 0.04 );
		m.normalNode = bumpMap( grain( 25.0, 2 ), float( 0.04 ) );
		return m;
	} )();
	M.int_white_gloss = gloss( 'int_white_gloss', '#e6e5e1', 0.22 );
	M.int_ceramic = gloss( 'int_ceramic', '#ecece9', 0.10, 1.0 );
	M.int_wood_oak = ( () => {
		const m = simple( 'int_wood_oak', '#b3895a', 0.55, 0.0, 0.0 );
		const g = mx_fractal_noise_float( positionWorld.mul( vec3( 3.0, 40.0, 3.0 ) ), 3, 2.0, 0.5, 1.0 );
		m.colorNode = vec3( ...SR( '#b3895a' ) ).mul( float( 1.0 ).add( g.mul( 0.16 ) ) );
		return m;
	} )();
	M.int_wood_walnut = ( () => {
		const m = simple( 'int_wood_walnut', '#4f3627', 0.48, 0.0, 0.0 );
		const g = mx_fractal_noise_float( positionWorld.mul( vec3( 3.0, 40.0, 3.0 ) ), 3, 2.0, 0.5, 1.0 );
		m.colorNode = vec3( ...SR( '#4f3627' ) ).mul( float( 1.0 ).add( g.mul( 0.22 ) ) );
		return m;
	} )();
	M.int_black = simple( 'int_black', '#111214', 0.40, 0.2, 0.0 );
	M.int_stone_dark = simple( 'int_stone_dark', '#3a3a3c', 0.32, 0.0, 0.08 );
	M.int_accent_red = simple( 'int_accent_red', '#8b2d29', 0.60, 0.0, 0.06 );
	M.int_pot = simple( 'int_pot', '#36322f', 0.60, 0.0, 0.08 );
	// the mint worktop and splashback of the render's kitchen
	M.int_mint = gloss( 'int_mint', '#a7c3b2', 0.30, 0.6 );
	M.int_brass = metalMat( 'int_brass', '#b08c55', 0.35, 0.85 );
	M.int_mirror = metalMat( 'int_mirror', '#e0e4e9', 0.03, 1.0 );
	M.int_glass = ( () => {
		const m = new THREE.MeshPhysicalNodeMaterial();
		m.name = 'int_glass';
		m.transparent = true;
		m.depthWrite = false;
		m.side = THREE.DoubleSide;
		m.colorNode = vec3( ...SR( '#cfe3ea' ) );
		// kept clear: from inside the flat you are meant to see the street
		m.opacityNode = float( 0.13 );
		m.roughnessNode = float( 0.04 );
		m.metalnessNode = float( 0.0 );
		return m;
	} )();

	/* ------------------------------------------------------------ x-ray
	 * The page fades one storey of block A's street front so the rooms
	 * behind it can be seen. Rather than a second set of materials, every
	 * piece of the shell carries one extra test: is this fragment inside
	 * the box the page has named - measured in the building's own frame, so
	 * a rotated block is exact and no neighbour is touched? If it is, the
	 * fragment is dropped on the alpha test, which costs no transparent
	 * pass and no sorting, and the shadow of that storey opens with it.
	 *
	 * Nothing here changes how anything looks until `amt` goes to 1: the
	 * box is empty and `opacityNode` is multiplied by one.
	 * -------------------------------------------------------------- */
	/* Two slots, because a floor that is shutting and a floor that is opening
	 * happen at the same moment: each carries its own pair of boxes (the
	 * street front and the gable), its own room box, and its own dial. The
	 * building's frame is shared - it is one building. */
	const xraySlot = () => ( {
		lo: uniform( new THREE.Vector3() ),         // the street front's box
		hi: uniform( new THREE.Vector3() ),         // ...z is world height
		glo: uniform( new THREE.Vector3() ),        // and the gable's, the end
		ghi: uniform( new THREE.Vector3() ),        // wall behind the hero type
		rlo: uniform( new THREE.Vector3() ),        // the rooms of that storey
		rhi: uniform( new THREE.Vector3() ),
		lift: uniform( 0 ),                         // ...and how much they glow
		fade: uniform( 0 ),                         // how far the wall has dissolved
		amt: uniform( 0 ),                          // ...and whether this slot is live
	} );
	const XRAY = {
		o: uniform( new THREE.Vector3() ),          // the block's near corner
		ex: uniform( new THREE.Vector3( 1, 0, 0 ) ),// along the street
		ey: uniform( new THREE.Vector3( 0, 0, 1 ) ),// into the plan
		skin: uniform( 0 ),                         // how deep the shallow cut goes
		seed: uniform( 0 ),                         // turns the dissolve's pattern
		slots: [ xraySlot(), xraySlot() ],
	};
	/* Two depths, because the front of a storey is built in two layers.
	 * The DEEP cut takes everything of the street front - the wall, the
	 * windows in it, the loggias and their rails, the balcony tiling and
	 * the glazing - back past the loggia's own back wall. The SHALLOW cut
	 * takes the skin the flat lines that wall with: the white lining, the
	 * inner sashes and the oak sills, which are the "inner wall and inner
	 * windows" left hanging in the opening when only the shell was dropped.
	 * It has to stay shallow because the same materials build the
	 * partitions and the furniture a metre further in, and those stand. */
	/* Two boxes, not one: the storey's street front, and the whole end wall
	 * round the corner from it. A floor is taken away as a floor, so both
	 * walls of it go - the gable is the one standing behind the hero's type
	 * and it opens for its full depth, not just the corner. */
	const _d = positionWorld.sub( XRAY.o );
	const _lx = dot( _d, XRAY.ex ), _ly = dot( _d, XRAY.ey ), _lz = positionWorld.y;
	/* A box in the building's frame is a FOOTPRINT and a HEIGHT, and they are
	 * asked separately here. The storey's street front and its gable share a
	 * height - they are one floor - while their plans differ, and asking the
	 * same footprint about a SECOND height then costs two steps instead of
	 * another twelve, which is what the fade below is built on. */
	const xrayFoot = ( lo, hi, hy ) => step( lo.x, _lx ).mul( step( _lx, hi.x ) )
		.mul( step( lo.y, _ly ) ).mul( step( _ly, hy ) );
	const xrayZ = ( lo, hi ) => step( lo, _lz ).mul( step( _lz, hi ) );
	const xrayBox = ( lo, hi, hy ) => xrayFoot( lo, hi, hy ).mul( xrayZ( lo.z, hi.z ) );
	/* The wall does not only part - the whole storey DISSOLVES while it
	 * parts, so what a visitor sees is a floor going translucent with the
	 * rooms rising through it, not a slot being cut in something solid.
	 *
	 * There is no per-fragment opacity to turn down here. The shell is
	 * opaque and the cut is a drop on the alpha test, which is the whole
	 * reason the opening costs no transparent pass and no sorting, so what
	 * fades is the FRACTION of fragments dropped rather than the alpha of
	 * each: at a dial of 0.4 two pixels in five of that storey's front are
	 * gone and the rest still stand. Interleaved gradient noise rather than
	 * a Bayer matrix - three multiplies and two fracts, and it distributes
	 * better at the fine end, where the temporal filter has to resolve it.
	 *
	 * `seed` turns the pattern every frame (the page bumps it in
	 * `floorStep`, by a golden-ratio step so successive frames never land on
	 * the same phase): a pattern that stands still is a screen door and the
	 * eye reads it as grain, while one that turns averages to a true fade
	 * over the few frames TRAA holds. One seed for the whole frame, not
	 * `time`, so the pre-pass's normals are stippled exactly like the beauty
	 * pass's colour.
	 *
	 * At rest the dial is exactly 0 or 1 and `step` is exactly 0 or 1 with
	 * it, so a parked frame is binary again and nothing of the still render
	 * moves by a bit. */
	const _stip = ( () => {
		const p = screenCoordinate.xy;
		const g = p.x.mul( 0.06711056 ).add( p.y.mul( 0.00583715 ) )
			.add( XRAY.seed ).fract();
		// held off 0 and 1 so a dial at either end is all or nothing
		return g.mul( 52.9829189 ).fract().mul( 0.96 ).add( 0.02 );
	} )();
	const stipple = ( c ) => step( _stip, c );
	/* `deep` is the whole front of the storey - wall, windows, balconies -
	 * and the shallow one is only the skin the flat lines it with, which has
	 * to stay a finger thick or the partitions go with it. The depth is per
	 * slot now, because each slot carries its own box. */
	/* A hovered storey answers over ONE plan at TWO heights. `lo.z..hi.z` is
	 * the parting line, which travels up and down from the middle of the
	 * floor and takes the wall cleanly away behind it. `rlo.z..rhi.z` is the
	 * whole storey, and over that the wall is not taken but FADED: `fade` is
	 * the fraction of its fragments the stipple drops, so the floor goes
	 * translucent - the rooms, the lamps and the balconies coming up through
	 * it - while the clean opening grows inside it. Both at once was the
	 * ask; either alone is a slot cut in a solid wall, or a wall that simply
	 * disappears. */
	const xrayAt = ( deep ) => {
		const one = ( S ) => max(
			xrayFoot( S.lo, S.hi, deep ? S.hi.y : XRAY.skin ),
			xrayFoot( S.glo, S.ghi, S.ghi.y ) )
			.mul( max( xrayZ( S.lo.z, S.hi.z ),
				xrayZ( S.rlo.z, S.rhi.z ).mul( S.fade ) ) )
			.mul( S.amt );
		return max( one( XRAY.slots[ 0 ] ), one( XRAY.slots[ 1 ] ) );
	};
	/* A third cut, over the whole storey rather than its front: the joinery
	 * the flat is fitted with. Seen from the street a door leaf and its
	 * handle are a carcase standing in a room, so they go with the windows
	 * and the balconies and leave the opening as rooms and furniture. The
	 * box is the storey's own, so the same materials elsewhere in the city -
	 * a lamp post, a car - are untouched. */
	const roomCut = XRAY.slots
		.map( S => xrayBox( S.rlo, S.rhi, S.rhi.y ).mul( S.fade ).mul( S.amt ) )
		.reduce( ( a, b ) => max( a, b ) );
	const cuts = [
		[ stipple( roomCut ), [ 'int_door_leaf', 'chrome', 'metal_dark' ] ],
		[ stipple( xrayAt( true ) ), [ 'plaster_dark', 'plaster_dark_b', 'concrete_loggia',
			'glass_window', 'glass_blind', 'glass_lit', 'glass_slot',
			'frame_bronze', 'frame_light', 'reveal_dark', 'rail_balcony',
			'int_glass', 'int_tile_white', 'int_curtain',
			'int_wall_loggia', 'int_accent_red' ] ],
		[ stipple( xrayAt( false ) ), [ 'int_wall', 'int_white_gloss', 'int_wood_oak' ] ],
	];
	for ( const [ cut, names ] of cuts )
		for ( const name of names ) {
			const m = M[ name ];
			if ( ! m || m.__xray ) continue;
			m.__xray = true;                  // plaster_light is plaster_dark
			m.opacityNode = ( m.opacityNode || float( 1 ) ).mul( cut.oneMinus() );
			m.alphaTest = 0.5;
		}

	/* The rooms of an opened storey have to read as lit - they stand in the
	 * building's own shadow and would otherwise be a grey slot. Three point
	 * lights did it and cost every lit pixel in the frame their own
	 * attenuation; this costs a multiply and an add, on the interior
	 * materials only. Each room glows in its own colour, so a parquet floor
	 * warms and a white wall brightens, which is what a lamp inside would
	 * do. `lift` is 0 until a floor opens. */
	/* Not a slab of emissive: a lamp in each flat. One sits in the middle of
	 * every unit along the row, high in the room, and the light falls off
	 * with the square of the distance to it, so the wall beside a lamp
	 * burns and the corners of the plan go dim. Two more things stop it
	 * reading as a shader: a hash on the unit's own number varies how hard
	 * each flat is lit - a building at dusk is never evenly lit - and the
	 * ceiling keeps a little more light than the floor, which is what a
	 * lamp hung high does. All of it is six multiplies on fragments that
	 * are inside the storey anyway. */
	const UNIT = 11.54, LAMP_Y = 4.2, LAMP_H = 0.78;
	const hash1 = ( n ) => sin( n.mul( 12.9898 ) ).mul( 43758.5453 ).fract();
	const roomLift = XRAY.slots.map( ( S ) => {
		const inside = xrayBox( S.rlo, S.rhi, S.rhi.y );
		const d = positionWorld.sub( XRAY.o );
		const lx = dot( d, XRAY.ex ), ly = dot( d, XRAY.ey );
		const span = S.rhi.z.sub( S.rlo.z ).max( float( 0.001 ) );
		const h = positionWorld.y.sub( S.rlo.z ).div( span );      // 0 floor, 1 ceiling
		const unit = lx.div( UNIT );
		const dx = unit.fract().sub( 0.5 ).mul( UNIT );            // to the lamp, along
		const dy = ly.sub( LAMP_Y );                               // ...into the plan
		const dz = h.sub( LAMP_H ).mul( span );                    // ...and in height
		const d2 = dx.mul( dx ).add( dy.mul( dy ) ).add( dz.mul( dz ) );
		const fall = float( 1 ).div( d2.mul( 0.055 ).add( 1 ) );
		const lit = hash1( unit.floor().add( 3.7 ) ).mul( 0.55 ).add( 0.72 );
		const up = h.mul( 0.35 ).add( 0.8 );                       // hung high
		return inside.mul( S.lift ).mul( fall ).mul( lit ).mul( up );
	} ).reduce( ( a, b ) => a.add( b ) );
	/* The brand's amber, in linear light: the lamp that comes on inside an
	 * opened storey. Each surface still glows through its own colour, so a
	 * parquet floor warms and a white wall takes the tint rather than being
	 * painted over, and the scale puts back the brightness the tint costs. */
	const GLOW_TINT = vec3( 0.787, 0.428, 0.142 ).mul( 2.1 );
	for ( const name of Object.keys( M ) ) {
		if ( ! name.startsWith( 'int_' ) ) continue;
		const m = M[ name ];
		if ( ! m || m.__lift ) continue;
		m.__lift = true;
		const c = m.color || { r: 1, g: 1, b: 1 };
		const base = m.colorNode || vec3( c.r, c.g, c.b );
		const glow = base.mul( GLOW_TINT ).mul( roomLift );
		m.emissiveNode = m.emissiveNode ? m.emissiveNode.add( glow ) : glow;
	}

	return { materials: M, SUN, SUNC, XRAY };

}
