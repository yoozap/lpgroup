// ---------------------------------------------------------------------------
// The sky.
//
// One model, written as a TSL function of a world direction, used twice:
//
//   * as `scene.backgroundNode`, evaluated per screen pixel. Nothing is
//     resampled from a texture, so the cirrus stays sharp however far the
//     camera pushes in and the blue gradient never bands;
//   * rendered once into a small equirectangular target that feeds the PMREM
//     - the image based light every material reads - and the glazing's own
//     sky lookup in materials.js, so a reflection and the sky behind it are
//     the same sky.
//
// The base is Preetham's analytic clear sky, evaluated in Yxy and converted to
// linear Rec.709. On top of it:
//
//   * a cirrus deck on a flat shell overhead. The view ray is intersected with
//     the shell, so the bands compress towards the horizon the way a real deck
//     does, and the noise is squashed along the band direction and domain
//     warped, which is what makes cirrus read as fibrous rather than blobby.
//   * a thin band of far cumulus sitting on the horizon, laid down *under* the
//     haze so distance veils it.
//   * the haze itself: in the photograph the horizon stays plainly blue, so
//     the wash is a pale blue, not the neutral grey a naive fog would give.
//   * the sun disc and its aureole - background only. The equirect leaves them
//     out, otherwise the PMREM would carry a second sun on top of the
//     SunLight that already casts the shadows.
// ---------------------------------------------------------------------------

import {
	Fn, vec2, vec3, vec4, float, uv, dot, max, pow, exp, mix, clamp, acos,
	smoothstep, normalize, fract, sin, saturate, screenCoordinate,
	equirectDirection, mx_fractal_noise_float,
} from 'three/tsl';

export const SKY = {
	turbidity: 2.25,
	exposure: 0.0315,
	// pale blue wash along the horizon. Measured off the reference: its sky is
	// still rgb(126,146,185) where it meets the roofline, a light blue - the
	// neutral grey this used to fade to was the one real colour error.
	haze: [ 0.300, 0.376, 0.520 ],
	hazeDepth: 0.56,      // how far up the wash reaches, in sin(elevation)
	hazeAmount: 0.86,     // as the CPU sky had it, so the IBL does not move
	// the last couple of degrees, where dust turns the blue slightly warm
	rim: [ 0.520, 0.500, 0.470 ],
	ground: [ 0.125, 0.117, 0.104 ],
	cirrus: 0.72,         // coverage of the high deck
	cirrusScale: 1.0,
	cirrusTurn: 0.70,     // radians the bands sweep across the sky
	cirrusStretch: 0.50,  // 1 is round, 0 would be an infinitely long streak
	cumulus: 0.50,        // the far band on the horizon
	cloudGain: 26.0,      // cloud radiance, in units of `exposure`
	sunGain: 14.0,
	saturation: 1.10,
	tint: [ 1, 1, 1 ],
	lift: 1.0,
	zenith: 0,
};

/**
 * What the sky looks like, as against what it does.
 *
 * These are read off the reference frame by frame - a deeper wash that climbs
 * much further up, a bluer, less green cast, and the top of the sky pulled
 * down, because the photograph's gradient between 47 and 32 degrees is
 * steeper than Preetham's. They are the grade on the *background only*. The
 * equirect that lights the building is built from SKY untouched, so none of
 * this can quietly relight the facade - which it did, by ten per cent, the
 * first time the haze went up.
 */
export const SKY_LOOK = {
	haze: [ 0.310, 0.415, 0.820 ],
	hazeDepth: 1.00,
	hazeAmount: 1.00,
	tint: [ 1.09, 0.955, 1.16 ],   // chroma, measured against the reference
	lift: 1.04,                    // overall level
	zenith: 0.21,                  // how much the top of the sky comes down
};

/**
 * Builds the sky as a TSL function of a world direction.
 * @param {Object} opts  sunDir (THREE.Vector3) plus any override of SKY.
 *        `disc` adds the sun itself - true for what you look at, false for
 *        what lights the scene.
 * @return {Function} ( dir ) => vec3, linear Rec.709 radiance
 */
export function makeSky( opts = {} ) {

	const o = { ...SKY, disc: true, ...opts };
	const { sunDir, turbidity: T, exposure } = o;

	const sy = sunDir.y;
	const thetaS = Math.acos( Math.min( 1, Math.max( - 1, sy ) ) );

	const AY = 0.1787 * T - 1.4630, BY = - 0.3554 * T + 0.4275;
	const CY = - 0.0227 * T + 5.3251, DY = 0.1206 * T - 2.5771;
	const EY = - 0.0670 * T + 0.3703;
	const Ax = - 0.0193 * T - 0.2592, Bx = - 0.0665 * T + 0.0008;
	const Cx = - 0.0004 * T + 0.2125, Dx = - 0.0641 * T - 0.8989;
	const Ex = - 0.0033 * T + 0.0452;
	const Ay = - 0.0167 * T - 0.2608, By = - 0.0950 * T + 0.0092;
	const Cy = - 0.0079 * T + 0.2102, Dy = - 0.0441 * T - 1.6537;
	const Ey = - 0.0109 * T + 0.0529;

	const t = thetaS, t2 = t * t, t3 = t2 * t;
	const chi = ( 4 / 9 - T / 120 ) * ( Math.PI - 2 * t );
	const Yz = ( 4.0453 * T - 4.9710 ) * Math.tan( chi ) - 0.2155 * T + 2.4192;
	const xz = ( 0.00166 * t3 - 0.00375 * t2 + 0.00209 * t ) * T * T +
		( - 0.02903 * t3 + 0.06377 * t2 - 0.03202 * t + 0.00394 ) * T +
		( 0.11693 * t3 - 0.21196 * t2 + 0.06052 * t + 0.25886 );
	const yz = ( 0.00275 * t3 - 0.00610 * t2 + 0.00317 * t ) * T * T +
		( - 0.04214 * t3 + 0.08970 * t2 - 0.04153 * t + 0.00516 ) * T +
		( 0.15346 * t3 - 0.26756 * t2 + 0.06670 * t + 0.26688 );

	// the zenith normalisation, on the CPU: Perez at theta = 0, gamma = thetaS
	const perezJS = ( A, B, C, D, E, ct, g ) =>
		( 1 + A * Math.exp( B / Math.max( ct, 0.012 ) ) ) *
		( 1 + C * Math.exp( D * g ) + E * Math.cos( g ) * Math.cos( g ) );
	const nY = perezJS( AY, BY, CY, DY, EY, 1, thetaS );
	const nx = perezJS( Ax, Bx, Cx, Dx, Ex, 1, thetaS );
	const ny = perezJS( Ay, By, Cy, Dy, Ey, 1, thetaS );

	const SUN = vec3( sunDir.x, sunDir.y, sunDir.z );
	const CLOUD_I = exposure * o.cloudGain;
	const SUN_I = exposure * o.sunGain * 60;
	const ca = Math.cos( o.cirrusTurn ), sa = Math.sin( o.cirrusTurn );

	/** Perez, on the GPU. ct is cos(theta), g the angle to the sun. */
	const perez = ( A, B, C, D, E, ct, g, cosG ) =>
		float( 1 ).add( float( A ).mul( exp( float( B ).div( ct ) ) ) ).mul(
			float( 1 ).add( float( C ).mul( exp( float( D ).mul( g ) ) ) )
				.add( float( E ).mul( cosG ).mul( cosG ) ) );

	/** signed fractal noise remapped to 0..1 */
	const fbm01 = ( p, oct, lac = 2.07, dim = 0.55 ) =>
		mx_fractal_noise_float( p, oct, lac, dim, 1.0 ).mul( 0.5 ).add( 0.5 );

	// ---------------------------------------------------------------- cirrus
	const cirrusAt = Fn( ( [ d ] ) => {

		// Where the ray crosses the deck. A true 1/sin(elevation) sends the
		// scale to infinity at the horizon and everything then converges on
		// the vanishing point as a fan of straight rays - which is exactly
		// what this looked like at first. The denominator is softened so the
		// deck still compresses with distance, about five to one top to
		// bottom, without collapsing into rays.
		const k = float( 1 ).div( d.y.max( 0 ).mul( 0.72 ).add( 0.17 ) );
		const px = d.x.mul( k ), pz = d.z.mul( k );
		// turn the deck, then draw it out along the length of the bands
		const q = vec2(
			px.mul( ca ).sub( pz.mul( sa ) ).mul( o.cirrusStretch ),
			px.mul( sa ).add( pz.mul( ca ) ) ).mul( o.cirrusScale ).toVar();

		// Two domain warps. A straight fbm gives even blobs and a single low
		// warp just slides whole bands sideways; the second, finer one is what
		// puts the hooks and feathered ends in.
		const w = q.add( vec2(
			fbm01( vec3( q.mul( 0.45 ), 11.3 ), 2 ).sub( 0.5 ),
			fbm01( vec3( q.mul( 0.45 ), 27.9 ), 2 ).sub( 0.5 ) ).mul( 0.85 ) )
			.add( vec2(
				fbm01( vec3( q.mul( 1.60 ), 5.1 ), 2 ).sub( 0.5 ),
				fbm01( vec3( q.mul( 1.60 ), 19.7 ), 2 ).sub( 0.5 ) ).mul( 0.28 ) ).toVar();

		const n = fbm01( vec3( w, 4.2 ), 5 );
		const cov = smoothstep( 0.47, 0.80, n );
		// a slow mask on top, so whole stretches of the sky stay empty the way
		// a real cirrus field does rather than wisping evenly everywhere
		const patch = smoothstep( 0.20, 0.62, fbm01( vec3( q.mul( 0.20 ), 2.6 ), 3 ) );
		// fine fibres across the band
		const fib = fbm01( vec3( w.mul( vec2( 4.6, 1.7 ) ), 8.7 ), 4, 2.2, 0.5 );
		const dens = cov.mul( patch ).mul( mix( float( 0.34 ), float( 1.0 ), fib ) );

		// gone by the horizon, where a deck is seen edge on and is simply haze
		return dens.mul( smoothstep( 0.015, 0.26, d.y ) ).mul( o.cirrus ).clamp( 0, 1 );

	} );

	// --------------------------------------------------------------- cumulus
	// A far, low band. Sparse on purpose: the reference is a clear day with a
	// single puff on the right, and the point here is depth, not weather.
	const cumulusAt = Fn( ( [ d ] ) => {

		const k = float( 1 ).div( max( d.y, 0.016 ) );
		const q = vec2( d.x, d.z ).mul( k ).mul( 0.17 ).toVar();
		const n = fbm01( vec3( q, 31.7 ), 4, 2.1 );
		const cov = smoothstep( 0.60, 0.82, n );
		const band = smoothstep( 0.004, 0.028, d.y ).mul( smoothstep( 0.30, 0.085, d.y ) );
		// lit tops, shaded bases: read the field again a little above
		const up = fbm01( vec3( q.add( vec2( 0.0, 0.10 ) ), 31.7 ), 4, 2.1 );
		return vec2( cov.mul( band ).mul( o.cumulus ).clamp( 0, 1 ),
			saturate( up.sub( n ).mul( 3.0 ).add( 0.55 ) ) );

	} );

	// ------------------------------------------------------------------ sky
	return Fn( ( [ rawDir ] ) => {

		const d = normalize( rawDir ).toVar();
		const ct = max( d.y, 0.012 ).toVar();
		const cosG = clamp( dot( d, SUN ), - 1, 1 ).toVar();
		const g = acos( cosG ).toVar();

		const Y = float( Yz ).mul( perez( AY, BY, CY, DY, EY, ct, g, cosG ) )
			.div( nY ).max( 0 ).mul( exposure ).toVar();
		const cx = float( xz ).mul( perez( Ax, Bx, Cx, Dx, Ex, ct, g, cosG ) ).div( nx ).toVar();
		const cy = float( yz ).mul( perez( Ay, By, Cy, Dy, Ey, ct, g, cosG ) ).div( ny ).max( 1e-4 ).toVar();

		const X = cx.div( cy ).mul( Y );
		const Z = float( 1 ).sub( cx ).sub( cy ).div( cy ).mul( Y );
		const col = vec3(
			X.mul( 3.2406 ).sub( Y.mul( 1.5372 ) ).sub( Z.mul( 0.4986 ) ),
			X.mul( - 0.9689 ).add( Y.mul( 1.8758 ) ).add( Z.mul( 0.0415 ) ),
			X.mul( 0.0557 ).sub( Y.mul( 0.2040 ) ).add( Z.mul( 1.0570 ) ) ).max( 0 ).toVar();

		// a touch of saturation back: Preetham at this turbidity reads a
		// little washed next to the photograph
		const lum0 = dot( col, vec3( 0.2126, 0.7152, 0.0722 ) );
		col.assign( mix( vec3( lum0 ), col, float( o.saturation ) ).max( 0 ) );

		const warm = saturate( cosG );

		// --- far cumulus, under the haze so distance veils it
		const cu = cumulusAt( d ).toVar();
		const cuCol = mix( vec3( 0.46, 0.49, 0.57 ), vec3( 1.00, 0.98, 0.94 ), cu.y )
			.mul( CLOUD_I * 0.92 );
		col.assign( mix( col, cuCol, cu.x ) );

		// --- cirrus
		const ci = cirrusAt( d ).toVar();
		const ciCol = mix( vec3( 0.70, 0.74, 0.82 ), vec3( 1.00, 0.97, 0.90 ),
			warm.mul( 0.55 ).add( 0.25 ) ).mul( CLOUD_I );
		col.assign( mix( col, ciCol, ci ) );

		if ( o.disc ) {
			// the disc is about half a degree across; the aureole is the
			// forward scattering around it
			const disc = smoothstep( 0.999905, 0.999975, cosG );
			const aureole = pow( warm, 900 ).mul( 0.30 ).add( pow( warm, 16 ).mul( 0.022 ) );
			col.addAssign( vec3( 1.00, 0.96, 0.90 ).mul( disc.mul( SUN_I ) ) );
			col.addAssign( vec3( 1.00, 0.95, 0.86 ).mul( aureole.mul( SUN_I * 0.5 ) ) );
		}

		// --- haze
		const h = pow( saturate( float( 1 ).sub( max( d.y, 0 ).div( o.hazeDepth ) ) ), 2.1 )
			.mul( o.hazeAmount ).toVar();
		col.assign( mix( col, vec3( ...o.haze ), h ) );
		// the last few degrees, slightly warm with dust
		const rim = pow( saturate( float( 1 ).sub( max( d.y, 0 ).mul( 14.0 ) ) ), 2.0 ).mul( 0.30 );
		col.assign( mix( col, vec3( ...o.rim ), rim ) );
		// --- grade (background only; SKY leaves all of this at identity)
		if ( o.zenith ) col.mulAssign( float( 1 ).sub( smoothstep( 0.52, 0.80, d.y ).mul( o.zenith ) ) );
		col.mulAssign( vec3( o.tint[ 0 ] * o.lift, o.tint[ 1 ] * o.lift, o.tint[ 2 ] * o.lift ) );

		// --- ground half: what bounces back up into the building
		const kg = saturate( d.y.negate().mul( 7.0 ) ).toVar();
		const gc = vec3( ...o.ground ).mul( 3.0 )
			.mul( float( 0.55 ).add( float( 0.45 ).mul( float( 1 ).sub( kg ) ) ) );
		col.assign( mix( col, gc, kg ) );

		return col.max( 0 );

	} );

}

/**
 * Screen space dither. 8 bit output bands badly across a sky this smooth, so
 * the background gets a fixed sub-quantum ripple; it costs nothing and the
 * banding goes.
 */
export function dither( colNode, amount = 0.004 ) {
	const p = screenCoordinate;
	const n = fract( sin( dot( p, vec2( 12.9898, 78.233 ) ) ).mul( 43758.5453 ) );
	return colNode.mul( float( 1 ).add( n.sub( 0.5 ).mul( amount ) ) );
}

/**
 * Renders the sky once into an equirectangular target, for the PMREM and for
 * the glazing's sky lookup. Half float, so the sun side keeps its range.
 */
export function skyEquirect( THREE, renderer, sky, width = 1024, height = 512 ) {

	const rt = new THREE.RenderTarget( width, height, {
		type: THREE.HalfFloatType,
		format: THREE.RGBAFormat,
		colorSpace: THREE.NoColorSpace,
		depthBuffer: false,
		stencilBuffer: false,
		generateMipmaps: false,
		minFilter: THREE.LinearFilter,
		magFilter: THREE.LinearFilter,
	} );

	const material = new THREE.NodeMaterial();
	material.name = 'Sky.equirect';
	// The WebGPU backend writes row 0 at the top of the viewport and samples
	// v = 0 from that same row, so the quad's own uv is already the uv the
	// PMREM and materials.js will read back: equirectDirection is the exact
	// inverse of the equirectUV they sample with, and nothing needs flipping.
	material.fragmentNode = vec4( sky( equirectDirection( uv() ) ), 1 );

	const quad = new THREE.QuadMesh( material );
	const prev = renderer.getRenderTarget();
	renderer.setRenderTarget( rt );
	quad.render( renderer );
	renderer.setRenderTarget( prev );

	rt.texture.mapping = THREE.EquirectangularReflectionMapping;
	rt.texture.wrapS = THREE.RepeatWrapping;
	rt.texture.wrapT = THREE.ClampToEdgeWrapping;
	rt.texture.colorSpace = THREE.NoColorSpace;

	return rt;

}
