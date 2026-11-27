/* ===================================================================== *
 *  The real building's floors, for the scene.
 *
 *  app.js draws; this knows. Everything here is read off the build's own
 *  files - web/scene_meta.json (the frame, the levels, the facades) and
 *  web/plan_meta.json (per level: the flats, their polygons, label points,
 *  rooms and doors; the corridor; the walls a body cannot pass) - so there
 *  is not one plan number typed into the page. If a level moves in the
 *  drawing, it moves here when the build is re-run, and nowhere else.
 *
 *  What lives here:
 *    - the plan frame: plan metres <-> browser world (CONTRACT.md "Frames")
 *    - the level / flat / room lookup over plan_meta.json, and the room
 *      facts the page needs from rooms.json (web/rooms_lite.json)
 *    - fetching an interior part (web/interior/<LEVEL>.glb, cores.glb) as
 *      bytes, once, with a retry - the files may be regenerated under a
 *      running page by the build
 *    - the welding of a part: one mesh per material for the whole level,
 *      with the flat each vertex belongs to baked in as `aunit` (the same
 *      trick `apivot` is), the hinged door leaves welded apart and stashed
 *      with their hinge from plan_meta
 *    - the floor view's drawing, as a patch on the interior's own copies of
 *      the materials: ink walls, the brand's amber floors, the common parts
 *      in paper, and one dial per flat that brings it back as modelled
 *    - the section cap (the walls cut at the plan's height, in ink) and the
 *      street's storey bands, both built from the meta
 *    - `hooks`: the seams other modules hang off (furniture, walking)
 *
 *  app.js keeps the state machine, the camera and the frame loop.
 * ===================================================================== */

import * as THREE from 'three/webgpu';
import {
	attribute, uniform, uniformArray, int, float, vec3, mix, smoothstep, oneMinus,
	screenCoordinate, step as atLeast,
} from 'three/tsl';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';

/* --------------------------------------------------------------- hooks
 * The seams the rest of the rebuild hangs off. Nothing here waits on any of
 * them: a hook nobody has registered is an empty list.
 *
 *   onFlatReveal( level, n, amount )  a flat in the floor view is being
 *       furnished by the hover or the open flat: amount 0..1 as it eases.
 *       The furniture kits (another module) grow their pieces off this.
 *   onLevelShown( level, group )      a level's interior is on screen
 *   onLevelHidden( level, group )     ...and is not any more
 *   onRoom( level, n, room )          the camera has been stood in a room
 *       (room = plan_meta room record, or null on the way out)
 *
 * And the questions walking needs answered: `shown()` is the level that is
 * on screen now, `groupOf( level )` its group (null when not resident). */
export const hooks = {
	onFlatReveal: [], onLevelShown: [], onLevelHidden: [], onRoom: [],
	fire( name, ...args ) {
		for ( const fn of this[ name ] || [] ) {
			try { fn( ...args ); } catch ( e ) { console.warn( 'levels hook ' + name + ':', e ); }
		}
	},
	shown: () => null,
	groupOf: () => null,
};

/* ----------------------------------------------------------- the frame
 * world = origin + ex * x + ey * y + up * z, plan metres in, world out.
 * The interiors are exported in Blender's local frame (x, -y, z), which the
 * glTF export turns into (x, z, y) - so the matrix that carries a part into
 * the world is the basis (ex, up, ey) on the origin. Its determinant is +1:
 * it is a rotation, nothing is turned inside out by it. */
export function makeFrame( meta ) {
	const F = meta && meta.frame;
	if ( ! F ) return null;
	const o = new THREE.Vector3( ...F.origin );
	const ex = new THREE.Vector3( ...F.ex ).normalize();
	const ey = new THREE.Vector3( ...F.ey ).normalize();
	const up = new THREE.Vector3( ...( F.up || [ 0, 1, 0 ] ) ).normalize();
	const matrix = new THREE.Matrix4().makeBasis( ex, up, ey ).setPosition( o );
	const _d = new THREE.Vector3();
	return {
		o, ex, ey, up, matrix,
		world( x, y, z = 0, out = new THREE.Vector3() ) {
			return out.copy( o ).addScaledVector( ex, x ).addScaledVector( ey, y ).addScaledVector( up, z );
		},
		plan( v ) {
			_d.copy( v ).sub( o );
			return [ _d.dot( ex ), _d.dot( ey ), _d.dot( up ) ];
		},
	};
}

/* ------------------------------------------------------------ polygons
 * plan_meta writes a polygon as { outline: [[x,y]..], holes: [[[x,y]..]..] }. */
export const ringOf = ( p ) => ( p && ( p.outline || p ) ) || [];
function inRing( r, x, y ) {
	let c = false;
	for ( let i = 0, j = r.length - 1; i < r.length; j = i ++ ) {
		const a = r[ i ], b = r[ j ];
		if ( ( a[ 1 ] > y ) !== ( b[ 1 ] > y )
			&& x < ( b[ 0 ] - a[ 0 ] ) * ( y - a[ 1 ] ) / ( b[ 1 ] - a[ 1 ] ) + a[ 0 ] ) c = ! c;
	}
	return c;
}
export function inPoly( p, x, y ) {
	if ( ! inRing( ringOf( p ), x, y ) ) return false;
	for ( const h of ( p && p.holes ) || [] ) if ( inRing( h, x, y ) ) return false;
	return true;
}
export function bboxOf( polys, into = null ) {
	const b = into || { x0: Infinity, y0: Infinity, x1: - Infinity, y1: - Infinity };
	for ( const p of polys ) for ( const q of ringOf( p ) ) {
		if ( q[ 0 ] < b.x0 ) b.x0 = q[ 0 ]; if ( q[ 0 ] > b.x1 ) b.x1 = q[ 0 ];
		if ( q[ 1 ] < b.y0 ) b.y0 = q[ 1 ]; if ( q[ 1 ] > b.y1 ) b.y1 = q[ 1 ];
	}
	return b;
}
function segDist2( x, y, a, b ) {
	const dx = b[ 0 ] - a[ 0 ], dy = b[ 1 ] - a[ 1 ];
	const l = dx * dx + dy * dy;
	let t = l ? ( ( x - a[ 0 ] ) * dx + ( y - a[ 1 ] ) * dy ) / l : 0;
	t = Math.max( 0, Math.min( 1, t ) );
	const ex = a[ 0 ] + t * dx - x, ey = a[ 1 ] + t * dy - y;
	return ex * ex + ey * ey;
}
/* The point of a polygon furthest from its edges - where a label reads as
 * belonging to the room rather than to its doorway. A grid search refined
 * twice; rooms are a few metres across, so it is a few hundred tests. */
export function poleOf( p ) {
	const b = bboxOf( [ p ] );
	if ( ! isFinite( b.x0 ) ) return [ 0, 0 ];
	const rings = [ ringOf( p ), ...( ( p && p.holes ) || [] ) ];
	const dist = ( x, y ) => {
		let m = Infinity;
		for ( const r of rings ) for ( let i = 0, j = r.length - 1; i < r.length; j = i ++ )
			m = Math.min( m, segDist2( x, y, r[ i ], r[ j ] ) );
		return m;
	};
	let best = [ ( b.x0 + b.x1 ) / 2, ( b.y0 + b.y1 ) / 2 ], bd = - 1;
	let cx = best[ 0 ], cy = best[ 1 ], w = b.x1 - b.x0, h = b.y1 - b.y0;
	for ( let pass = 0; pass < 3; pass ++ ) {
		const N = 12;
		for ( let i = 0; i <= N; i ++ ) for ( let j = 0; j <= N; j ++ ) {
			const x = cx - w / 2 + w * i / N, y = cy - h / 2 + h * j / N;
			if ( ! inPoly( p, x, y ) ) continue;
			const d = dist( x, y );
			if ( d > bd ) { bd = d; best = [ x, y ]; }
		}
		cx = best[ 0 ]; cy = best[ 1 ]; w /= 4; h /= 4;
	}
	return best;
}

/* ------------------------------------------------------------- the data
 * plan_meta.json is 1.4 MB (262 KB on the wire), so it is not part of the
 * boot: it is asked for the first time anything wants a level. Re-read on
 * failure rather than cached as a failure - the build may be rewriting it. */
let planReq = null, liteReq = null;
/* JSON_CACHE (step 2-storey): on the sales page (body data-embed="1") the
 * plan JSON is fetched under the server's own caching - nginx sends
 * must-revalidate and an ETag, so a repeat visit gets a 304 and an edited
 * file is still picked up; serve.py sends no-store, so dev is unchanged.
 * The render lab keeps no-store. `?jsoncache=old` restores no-store. */
export const JSON_CACHE = typeof document !== 'undefined' && !! document.body && document.body.dataset.embed === '1'
	&& new URLSearchParams( location.search ).get( 'jsoncache' ) !== 'old';
export const jsonInit = () => JSON_CACHE ? {} : { cache: 'no-store' };
const index = { byId: new Map(), byN: new Map() };
export function planMeta() {
	if ( planReq ) return planReq;
	planReq = ( async () => {
		for ( let k = 0; k < 3; k ++ ) {
			try {
				const r = await fetch( './plan_meta.json', jsonInit() );
				if ( ! r.ok ) throw new Error( 'plan_meta.json ' + r.status );
				const m = await r.json();
				indexPlan( m );
				return m;
			} catch ( e ) {
				if ( k === 2 ) { planReq = null; throw e; }
				await new Promise( r => setTimeout( r, 400 * ( k + 1 ) ) );
			}
		}
	} )();
	return planReq;
}
function indexPlan( m ) {
	index.byId.clear(); index.byN.clear();
	for ( const L of m.levels || [] ) {
		const units = ( L.flats || [] ).map( f => ( { ...f, office: false } ) )
			.concat( ( L.offices || [] ).map( f => ( { ...f, office: true } ) ) );
		/* The unit's place in its level, from 1 - `aunit` 0 is the level's
		 * own (corridor, party walls, cores). This is the number the shader
		 * looks its dial up by, so it is fixed when the index is built and
		 * the weld reads it from here. */
		units.forEach( ( u, i ) => { u.k = i + 1; u.level = L.id; u.key = u.office ? 'o' + u.n : u.n; } );
		L.units = units;
		L.byToken = new Map( units.map( u => [ u.token || ( u.office ? 'o' + u.n : 'u' + u.n ), u ] ) );
		index.byId.set( L.id, L );
		for ( const u of units ) if ( ! u.office ) index.byN.set( String( u.n ), u );
	}
}
export const levelById = ( id ) => index.byId.get( id ) || null;
export const flatByN = ( n ) => index.byN.get( String( n ) ) || null;
export const planReady = () => index.byId.size > 0;

/* The room facts rooms.json has and plan_meta does not (its label point, its
 * camera stance, its Georgian name): tools/gen_rooms_lite.py. Optional - a
 * room without them gets its pole and a stance worked out here. */
export function roomsLite() {
	if ( liteReq ) return liteReq;
	liteReq = fetch( './rooms_lite.json', jsonInit() )
		.then( r => r.ok ? r.json() : { rooms: {} } )
		.then( j => j.rooms || {} )
		.catch( () => { liteReq = null; return {}; } );
	return liteReq;
}

/* A room the sheets draw with no name and no kind (nine of them: the third
 * bedroom-sized room of the 2-bedroom stack, 14 m2, and the second room of
 * flats 49/112/133) is "Room N": its place among the flat's living rooms,
 * bedrooms and unnamed rooms, counted in plan order - so flat 41's is Room 4
 * of a living room and two bedrooms. Not a guess at what it is for. */
export function roomNumber( unit, i ) {
	const rooms = ( unit && unit.rooms ) || [];
	if ( ! rooms[ i ] || rooms[ i ].name ) return null;
	let n = 0;
	for ( let k = 0; k <= i; k ++ ) if ( ! rooms[ k ].name || /^(living|bed)/.test( rooms[ k ].kind || '' ) ) n ++;
	return { name: 'Room ' + n, ka: 'ოთახი ' + n, n };
}

/* One flat's rooms as the page shows them: a label point, a name in both
 * languages, and a stance - the eye 1.6 m over the floor and a point it
 * looks at. plan_meta's own fields win if the build ever writes them. */
export function roomsOf( unit, lite ) {
	const mine = ( lite && lite[ unit.key ] ) || {};
	return ( unit.rooms || [] ).map( ( r, i ) => {
		const L = r.rooms_id ? mine[ r.rooms_id ] : null;
		const label = r.label || ( L && L[ 0 ] != null ? [ L[ 0 ], L[ 1 ] ] : poleOf( r.poly ) );
		let eye = null, look = null;
		if ( r.stance && r.stance.eye ) { eye = r.stance.eye; look = r.stance.look || r.stance.at; }
		else if ( L && L[ 2 ] != null ) { eye = [ L[ 2 ], L[ 3 ], L[ 4 ] ]; look = [ L[ 5 ], L[ 6 ], L[ 7 ] ]; }
		if ( ! eye ) {
			/* No stance written: stand on the label point and look down the
			 * room's longest view, which is the corner of its box furthest
			 * from where the eye is. */
			const b = bboxOf( [ r.poly ] );
			const far = [ [ b.x0, b.y0 ], [ b.x1, b.y0 ], [ b.x0, b.y1 ], [ b.x1, b.y1 ] ]
				.sort( ( p, q ) => Math.hypot( q[ 0 ] - label[ 0 ], q[ 1 ] - label[ 1 ] )
					- Math.hypot( p[ 0 ] - label[ 0 ], p[ 1 ] - label[ 1 ] ) )[ 0 ];
			eye = [ label[ 0 ], label[ 1 ], 1.6 ];
			look = [ far[ 0 ], far[ 1 ], 1.2 ];
		}
		const nm = r.name ? null : roomNumber( unit, i );
		return {
			i, kind: r.kind || 'room', name: r.name || ( nm ? nm.name : 'Room' ),
			ka: r.name_ka || ( L && L[ 8 ] ) || ( nm && nm.ka ) || null,
			label, eye, look: look || [ label[ 0 ] + 1, label[ 1 ], 1.2 ],
			area: r.area, poly: r.poly,
		};
	} );
}

/* ---------------------------------------------------------- the parts
 * An interior part is fetched as bytes once per page. The bytes are kept
 * only until parsed; the parsed level is what residency is counted in. */
const bytesSeen = new Map();
export const partBytes = () => Object.fromEntries( bytesSeen );
export async function fetchPart( name ) {
	let last = null;
	for ( let k = 0; k < 3; k ++ ) {
		try {
			const r = await fetch( './interior/' + name + '.glb' );
			if ( ! r.ok ) throw new Error( name + '.glb ' + r.status );
			const buf = await r.arrayBuffer();
			bytesSeen.set( name, buf.byteLength );
			return buf;
		} catch ( e ) {
			last = e;
			await new Promise( r => setTimeout( r, 500 * ( k + 1 ) ) );
		}
	}
	throw last;
}

/* The node a mesh belongs to, by the build's own naming (the glTF loader
 * hangs the primitives of a multi-material node under a group of its
 * name). */
function nodeName( o ) {
	for ( let n = o; n; n = n.parent ) if ( /^in_/.test( n.name || '' ) ) return n.name;
	return o.name || '';
}
/* `in_L03_u47-a_walls__int_wall` -> 'u47-a'; `in_L01_o7_..` -> 'o7';
 * `in_L00_C1_..` -> 'C1'; level-owned pieces carry no owner. */
const OWNER = /^in_(?:L\d\d|P-1|ROOF|C\d)_(u[^_]+|o\d+|C\d|podium)_/;
export const SWING = /_swing__/;
/* ...and the other things that move: the lift cars (`in_C1_lift1_car__..`)
 * and their landing doors (`in_C1_lift1_L05_door__..`), CONTRACT "Cores". */
export const LIFT_CAR = /_lift\d+_car__/;
export const LIFT_DOOR = /_lift\d+_(?:L\d\d|P-1|ROOF)_door2?__/;
/* The lift's lamps: the landing's dot-matrix digits and call arrows, and the
 * car's own display. The build bakes them as fixed text; the page draws them
 * live instead (app.js `liftKit`), from the black glass they sit on. */
const LIFT_LED = /_lift\d+_(?:L\d\d|P-1|ROOF)_led__/;
const LIFT_IND = /_lift\d+_(?:L\d\d|P-1|ROOF)_ind__/;
const CAR_LIVE = ( y ) => ( y > 1.49 && y < 1.60 ) || y > 2.12;   // the car's display and its arrows, over its floor
const MOVES = ( n ) => SWING.test( n ) || LIFT_CAR.test( n ) || LIFT_DOOR.test( n );
const CEILING = /_ceiling__/, CEILING_DROP = 0.015;

/* The weld. Every mesh of the part is put into world metres and merged per
 * material - per material AND swing, so a door leaf is never welded into the
 * frame it hangs in - keeping position and normal, and adding `aunit`: the
 * owning flat's place in its level (0 for anything the level owns). That
 * one float per vertex is what lets a whole level be one draw per material
 * and still light a single flat.
 *
 * Returns { meshes, doors, tris } - the meshes not yet in any group. */
export function weldPart( root, level, mats, onMissing ) {
	root.updateMatrixWorld( true );
	const by = new Map();
	const doors = [];
	const missing = new Set();
	const lift = { ind: new Map(), car: new Map() };
	root.traverse( ( o ) => {
		if ( ! o.isMesh ) return;
		const src = Array.isArray( o.material ) ? o.material[ 0 ] : o.material;
		const mname = ( ( src && src.name ) || '' ).replace( /\.\d+$/, '' );
		const name = nodeName( o );
		if ( LIFT_LED.test( name ) ) return;
		const car = LIFT_CAR.test( name );
		/* A car's surfaces take their grain in the car's own frame
		 * (`lift_*`, materials.js): a world-space grain stood still while
		 * the walls rode through it, and the walls looked to slide. */
		const mat = ( car && mats( 'lift_' + mname ) ) || mats( mname );
		if ( ! mat ) { missing.add( mname ); return; }
		const own = OWNER.exec( name );
		const unit = ( own && level && level.byToken.get( own[ 1 ] ) ) || null;
		const swing = MOVES( name );
		const g = o.geometry.clone().applyMatrix4( o.matrixWorld );
		/* A ceiling is let down 15 mm. L10's ceilings (z + 3.0 = +37.5) lie
		 * exactly in the plane of the street file's roof slab underside
		 * (`A_roof`/`B_roof`, 37.5..37.81, black plaster), and two downward
		 * faces at one depth fight: the top floor's rooms came out with jagged
		 * black ceilings (build 3, tour B). 15 mm is invisible from 1.6 m and
		 * puts the ceiling in front of anything the envelope builds at the
		 * ceiling's height, whatever the street file does about it. */
		if ( CEILING.test( name ) ) g.translate( 0, - CEILING_DROP, 0 );
		for ( const a of Object.keys( g.attributes ) )
			if ( a !== 'position' && a !== 'normal' ) g.deleteAttribute( a );
		if ( ! g.getAttribute( 'normal' ) ) g.computeVertexNormals();
		if ( LIFT_IND.test( name ) ) lift.ind.set( name, g.getAttribute( 'position' ).array.slice() );
		if ( car && mname === 'int_black' ) lift.car.set( name, g.getAttribute( 'position' ).array.slice() );
		if ( car && mname === 'neon_orange' ) dropTris( g, CAR_LIVE );
		const n = g.getAttribute( 'position' ).count;
		g.setAttribute( 'aunit', new THREE.BufferAttribute(
			new Float32Array( n ).fill( unit ? unit.k : 0 ), 1 ) );
		g.morphAttributes = {};
		if ( swing ) {
			/* Not welded here: `makeMovers` welds whatever of these is at
			 * rest and hangs the rest on their hinges / in their shafts.
			 * plan_meta has a leaf's hinge, width and headings by node name. */
			const rec = level && findDoor( level, name );
			doors.push( { node: name, mat: mname, material: mat, unit: unit ? unit.n : null, door: rec, geo: g,
				kind: LIFT_CAR.test( name ) ? 'car' : LIFT_DOOR.test( name ) ? 'landing' : 'leaf' } );
			return;
		}
		const key = mname;
		if ( ! by.has( key ) ) by.set( key, { mat, swing, geos: [] } );
		by.get( key ).geos.push( g );
	} );
	if ( missing.size && onMissing ) onMissing( [ ...missing ] );
	const meshes = [];
	let tris = 0;
	for ( const { mat, swing, geos } of by.values() ) {
		// all indexed or none: mergeGeometries refuses a mix with a null
		const mixed = geos.some( g => ! g.index ) && geos.some( g => g.index );
		const list = mixed ? geos.map( g => g.index ? g.toNonIndexed() : g ) : geos;
		let merged = null;
		try { merged = BufferGeometryUtils.mergeGeometries( list, false ); } catch ( e ) { merged = null; }
		if ( ! merged ) { console.warn( 'levels: weld refused for', mat.name ); continue; }
		merged.computeBoundingSphere();
		tris += ( merged.index ? merged.index.count : merged.getAttribute( 'position' ).count ) / 3;
		const mesh = new THREE.Mesh( merged, mat );
		mesh.name = 'lv_' + mat.name + ( swing ? '_swing' : '' );
		mesh.castShadow = mesh.receiveShadow = true;
		mesh.userData.swing = swing;
		meshes.push( mesh );
		// the stashed leaves keep their own geometry; the rest is spent
		if ( ! swing ) for ( const g of list ) g.dispose();
	}
	return { meshes, doors, tris, lift };
}
/* Take out of `g` (world metres, y up) every triangle whose centroid
 * height `drop` says goes. */
function dropTris( g, drop ) {
	const P = g.getAttribute( 'position' ), I = g.index;
	const n = I ? I.count : P.count, keep = [];
	for ( let t = 0; t < n; t += 3 ) {
		const a = I ? I.getX( t ) : t, b = I ? I.getX( t + 1 ) : t + 1, c = I ? I.getX( t + 2 ) : t + 2;
		if ( ! drop( ( P.getY( a ) + P.getY( b ) + P.getY( c ) ) / 3 ) ) keep.push( a, b, c );
	}
	g.setIndex( keep );
}
/* Everything of a part that moves - door leaves, lift cars, landing doors -
 * kept as its own geometry and welded per material only while at REST, so a
 * whole level of shut leaves is still one draw per material. A node that is
 * moved (`set( node, matrix )`, a world matrix applied to its world-space
 * geometry) is taken out of the weld and drawn on its own, with the SAME
 * material, so it costs a draw and never a pipeline; `set( node, null )`
 * puts it back. `flush()` re-welds the rest once a frame if anything came
 * or went - a few milliseconds over a level's 170 leaves, and only on the
 * frame a door starts to open or comes back shut. */
const mergeAll = ( geos ) => {
	const mixed = geos.some( g => ! g.index ) && geos.some( g => g.index );
	const list = mixed ? geos.map( g => g.index ? g.toNonIndexed() : g ) : geos;
	let m = null;
	try { m = BufferGeometryUtils.mergeGeometries( list, false ); } catch ( e ) { m = null; }
	if ( mixed ) for ( const g of list ) if ( ! geos.includes( g ) ) g.dispose();
	return m;
};
const MOVER_LEAK = typeof location !== 'undefined' && new URLSearchParams( location.search ).get( 'moverleak' ) === '1';
export function makeMovers( group, list ) {
	const byNode = new Map();
	for ( const d of list ) {
		if ( ! byNode.has( d.node ) ) byNode.set( d.node, { node: d.node, kind: d.kind, door: d.door, parts: [] } );
		byNode.get( d.node ).parts.push( { mat: d.material, geo: d.geo } );
	}
	const out = new Map();
	let rest = [], dirty = true;
	/* MOVER_LEAK: a mesh taken out here is told it is gone ('dispose' on the
	 * OBJECT - three r186 lets a render object go on that, not on its
	 * geometry's), a few frames later, so its replacement has drawn first and
	 * holds the pipeline both share. `?moverleak=1` keeps them all, as before. */
	let dead = [];
	const bury = ( all ) => {
		const t = performance.now();
		dead = dead.filter( ( d ) => { if ( ! all && t - d.t < 150 ) return true; d.m.dispatchEvent( { type: 'dispose' } ); return false; } );
	};
	function rebuild() {
		for ( const m of rest ) { m.removeFromParent(); m.geometry.dispose(); if ( ! MOVER_LEAK ) dead.push( { m, t: performance.now() } ); }
		rest = [];
		const by = new Map();
		for ( const [ n, N ] of byNode ) {
			if ( out.has( n ) ) continue;
			for ( const p of N.parts ) { if ( ! by.has( p.mat ) ) by.set( p.mat, [] ); by.get( p.mat ).push( p.geo ); }
		}
		for ( const [ mat, geos ] of by ) {
			const g = mergeAll( geos );
			if ( ! g ) { console.warn( 'levels: movers weld refused for', mat.name ); continue; }
			g.computeBoundingSphere();
			const mesh = new THREE.Mesh( g, mat );
			mesh.name = 'lv_' + mat.name + '_swing';
			mesh.castShadow = mesh.receiveShadow = true;
			mesh.frustumCulled = false;
			mesh.userData.swing = true;
			group.add( mesh );
			rest.push( mesh );
		}
		dirty = false;
	}
	rebuild();
	return {
		nodes: byNode,
		get out() { return out; },
		set( node, matrix ) {
			const N = byNode.get( node );
			if ( ! N ) return false;
			let o = out.get( node );
			if ( ! matrix ) {
				if ( o ) { for ( const m of o.meshes ) { m.removeFromParent(); if ( ! MOVER_LEAK ) dead.push( { m, t: performance.now() } ); } out.delete( node ); dirty = true; }
				return true;
			}
			if ( ! o ) {
				o = { meshes: N.parts.map( ( p ) => {
					const m = new THREE.Mesh( p.geo, p.mat );
					m.name = 'lv_' + node;
					m.matrixAutoUpdate = false;
					m.castShadow = m.receiveShadow = true;
					m.frustumCulled = false;
					group.add( m );
					return m;
				} ) };
				out.set( node, o );
				dirty = true;
			}
			for ( const m of o.meshes ) { m.matrix.copy( matrix ); m.matrixWorldNeedsUpdate = true; }
			return true;
		},
		flush() { if ( dead.length ) bury(); if ( dirty ) { rebuild(); return true; } return false; },
		dispose() {
			bury( true );
			for ( const m of rest ) { m.dispatchEvent( { type: 'dispose' } ); m.geometry.dispose(); }
			for ( const o of out.values() ) for ( const m of o.meshes ) m.dispatchEvent( { type: 'dispose' } );
			for ( const N of byNode.values() ) for ( const p of N.parts ) p.geo.dispose();
		},
	};
}

/* ------------------------------------------------------- the furniture
 * web/interior/furn/<LEVEL>.glb: one node per piece the architect drew,
 * its origin the piece's foot, instances of one mesh per kind and size
 * class (furnish report). It is NOT welded - the weld would throw away the
 * instancing and the chairs' UVs - but drawn as one InstancedMesh per mesh
 * and material, every piece of the level an instance. Each piece keeps its
 * placed matrix, and a piece is grown out of the floor by scaling it about
 * its own foot: `reveal( token, amount )` for one flat (the floor view's
 * hover, staggered by the reveal order index.json gives), `all( v )` for the
 * whole level (walking). `heights` is each node's top over its foot, for
 * the collision (walk.js `furnitureSolids`). */
const FURN_SPREAD = 0.6;
const FURN_GRAPH_OLD = typeof location !== 'undefined' && new URLSearchParams( location.search ).get( 'furngraph' ) === 'old';
export function buildFurniture( root, lvIndex, mats, onMissing ) {
	root.updateMatrixWorld( true );
	const sets = new Map(), heights = new Map(), missing = new Set();
	const piece = new Map();
	for ( const [ key, U ] of Object.entries( ( lvIndex && lvIndex.units ) || {} ) )
		for ( const p of U.pieces || [] ) piece.set( p.node, { token: U.token || ( ( U.office ? 'o' : 'u' ) + key ), p } );
	root.traverse( ( o ) => {
		if ( ! o.isMesh ) return;
		const src = Array.isArray( o.material ) ? o.material[ 0 ] : o.material;
		const mname = ( ( src && src.name ) || '' ).replace( /\.\d+$/, '' );
		const mat = mats( mname );
		if ( ! mat ) { missing.add( mname ); return; }
		const name = nodeName( o );
		if ( ! o.geometry.boundingBox ) o.geometry.computeBoundingBox();
		heights.set( name, Math.max( heights.get( name ) || 0, o.geometry.boundingBox.max.y * o.scale.y ) );
		const key = o.geometry.uuid + '|' + mname;
		if ( ! sets.has( key ) ) sets.set( key, { geo: o.geometry, mat, items: [] } );
		sets.get( key ).items.push( { node: name, m: o.matrixWorld.clone() } );
	} );
	if ( missing.size && onMissing ) onMissing( [ ...missing ] );
	const group = new THREE.Group();
	group.name = 'furniture';
	const inst = new THREE.Group();
	inst.name = 'furniture_instanced';
	group.add( inst );
	const units = new Map();
	let tris = 0;
	/* One plain Mesh a piece, sharing its set's geometry - NOT an
	 * InstancedMesh a set. three keys an instanced object's shader build on
	 * the object itself, so 170 instanced meshes were 500 builds a level:
	 * 4-5 s of compile, 700 MB of node builders while the level was in, and
	 * 280 MB of them left behind every time one was let go. A plain mesh
	 * shares its build with every other of its material, and only the flat
	 * under the pointer is drawn at all. */
	const reps = [];
	for ( const S of sets.values() ) {
		S.items.forEach( ( it, i ) => {
			const mesh = new THREE.Mesh( S.geo, S.mat );
			mesh.name = 'furn_' + S.mat.name;
			mesh.castShadow = mesh.receiveShadow = true;
			mesh.frustumCulled = false;
			mesh.matrixAutoUpdate = false;
			mesh.matrix.copy( it.m );
			mesh.visible = false;
			if ( i === 0 ) reps.push( mesh );
			const P = piece.get( it.node );
			const token = P ? P.token : ( /_(u[^_]+|o\d+)_furn_/.exec( it.node ) || [] )[ 1 ] || '?';
			if ( ! units.has( token ) ) units.set( token, [] );
			units.get( token ).push( { mesh, base: it.m, order: P ? P.p.order : 99, room: P ? P.p.room_index : 0, s: 0, node: it.node } );
			inst.add( mesh );
		} );
		tris += ( S.geo.index ? S.geo.index.count : S.geo.getAttribute( 'position' ).count ) / 3 * S.items.length;
	}
	/* ...and the same pieces WELDED, one mesh per material, for a level a
	 * visitor walks through with every flat furnished: the instanced set is
	 * one draw per mesh and size class - about seventy-five a level, two
	 * passes each - and a walk never animates a piece, so it does not need
	 * them apart. Built once, the first time it is asked for. Position and
	 * normal only, as every weld here (plus the UVs where a material has a
	 * map); a material whose pieces will not weld stays instanced. */
	let weld = null;
	function welded() {
		if ( weld ) return weld;
		weld = new THREE.Group();
		weld.name = 'furniture_welded';
		weld.visible = false;
		const byMat = new Map();
		for ( const S of sets.values() ) {
			const keepUv = !! ( S.mat.map || S.mat.normalMap || S.mat.roughnessMap || S.mat.aoMap );
			if ( ! byMat.has( S.mat ) ) byMat.set( S.mat, { keepUv, geos: [], sets: [] } );
			const E = byMat.get( S.mat );
			E.sets.push( S );
			for ( const it of S.items ) {
				const g = S.geo.clone().applyMatrix4( it.m );
				for ( const a of Object.keys( g.attributes ) )
					if ( a !== 'position' && a !== 'normal' && ! ( keepUv && a === 'uv' ) ) g.deleteAttribute( a );
				g.morphAttributes = {};
				E.geos.push( g );
			}
		}
		for ( const [ mat, E ] of byMat ) {
			const m = mergeAll( E.geos );
			for ( const g of E.geos ) g.dispose();
			if ( ! m ) { E.inst = true; continue; }
			m.computeBoundingSphere();
			const mesh = new THREE.Mesh( m, mat );
			mesh.name = 'furn_weld_' + mat.name;
			mesh.castShadow = mesh.receiveShadow = true;
			mesh.frustumCulled = false;
			weld.add( mesh );
		}
		// the materials that would not weld keep their instanced meshes on
		weld.userData.keepInst = new Set( [ ...byMat ].filter( ( [ , E ] ) => E.inst ).map( ( [ mat ] ) => mat ) );
		group.add( weld );
		return weld;
	}
	/* The same weld, sliced: the welded meshes are written straight into one
	 * preallocated array per attribute and material - no clone, no
	 * applyMatrix4 copy, no merge - in the order `welded()` writes them, with
	 * the same arithmetic (Vector3.applyMatrix4 / applyNormalMatrix), and a
	 * frame is let through whenever SLICE_MS has gone. The sync weld was one
	 * 100-270 ms task on every storey a walk loads. A material whose sets do
	 * not line up (mixed indexing, differing attributes or types) is welded
	 * the old way, so the result is what `welded()` would have built. */
	let weldJob = null, gone = false;
	function weldedAsync( yieldFn, SLICE_MS = 8 ) {
		if ( weld ) return Promise.resolve( weld );
		if ( weldJob ) return weldJob;
		weldJob = ( async () => {
			const out = new THREE.Group();
			out.name = 'furniture_welded';
			out.visible = false;
			const byMat = new Map();
			for ( const S of sets.values() ) {
				const keepUv = !! ( S.mat.map || S.mat.normalMap || S.mat.roughnessMap || S.mat.aoMap );
				if ( ! byMat.has( S.mat ) ) byMat.set( S.mat, { keepUv, sets: [] } );
				byMat.get( S.mat ).sets.push( S );
			}
			let t0 = performance.now();
			const tick = async () => { if ( performance.now() - t0 > SLICE_MS ) { await yieldFn(); t0 = performance.now(); } };
			const keepInst = new Set();
			const _v = new THREE.Vector3(), _nm = new THREE.Matrix3();
			for ( const [ mat, E ] of byMat ) {
				const names = ( g ) => Object.keys( g.attributes ).filter( a => a === 'position' || a === 'normal' || ( E.keepUv && a === 'uv' ) ).sort().join();
				const g0 = E.sets[ 0 ].geo, nm0 = names( g0 );
				const same = E.sets.every( S => names( S.geo ) === nm0 && !! S.geo.index === !! g0.index
					&& [ 'position', 'normal', 'uv' ].every( a => {
						const A = S.geo.attributes[ a ], B = g0.attributes[ a ];
						if ( ! B || ! nm0.split( ',' ).includes( a ) ) return true;
						return A.itemSize === B.itemSize && !! A.normalized === !! B.normalized && ! A.isInterleavedBufferAttribute
							&& A.array.constructor === B.array.constructor && ( a === 'uv' || A.array instanceof Float32Array );
					} ) );
				let geo = null;
				if ( ! same ) {
					// the old way, for this material alone
					const geos = [];
					for ( const S of E.sets ) for ( const it of S.items ) {
						const g = S.geo.clone().applyMatrix4( it.m );
						for ( const a of Object.keys( g.attributes ) )
							if ( a !== 'position' && a !== 'normal' && ! ( E.keepUv && a === 'uv' ) ) g.deleteAttribute( a );
						g.morphAttributes = {};
						geos.push( g );
					}
					geo = mergeAll( geos );
					for ( const g of geos ) g.dispose();
					await tick();
				} else {
					const has = nm0.split( ',' );
					let V = 0, I = 0;
					for ( const S of E.sets ) {
						V += S.geo.attributes.position.count * S.items.length;
						if ( g0.index ) I += S.geo.index.count * S.items.length;
					}
					const pos = new Float32Array( V * 3 );
					const nor = has.includes( 'normal' ) ? new Float32Array( V * 3 ) : null;
					const uvA = has.includes( 'uv' ) ? g0.attributes.uv : null;
					const uv = uvA ? new uvA.array.constructor( V * uvA.itemSize ) : null;
					const idx = g0.index ? ( V > 65535 ? new Uint32Array( I ) : new Uint16Array( I ) ) : null;
					let vo = 0, io = 0;
					for ( const S of E.sets ) {
						const P = S.geo.attributes.position.array, N = nor && S.geo.attributes.normal.array;
						const U = uv && S.geo.attributes.uv.array, X = idx && S.geo.index;
						const n = S.geo.attributes.position.count;
						for ( const it of S.items ) {
							const e = it.m.elements;
							for ( let i = 0; i < n; i ++ ) {
								const x = P[ i * 3 ], y = P[ i * 3 + 1 ], z = P[ i * 3 + 2 ];
								const w = 1 / ( e[ 3 ] * x + e[ 7 ] * y + e[ 11 ] * z + e[ 15 ] );
								const o = ( vo + i ) * 3;
								pos[ o ] = ( e[ 0 ] * x + e[ 4 ] * y + e[ 8 ] * z + e[ 12 ] ) * w;
								pos[ o + 1 ] = ( e[ 1 ] * x + e[ 5 ] * y + e[ 9 ] * z + e[ 13 ] ) * w;
								pos[ o + 2 ] = ( e[ 2 ] * x + e[ 6 ] * y + e[ 10 ] * z + e[ 14 ] ) * w;
							}
							if ( N ) {
								_nm.getNormalMatrix( it.m );
								const q = _nm.elements;
								for ( let i = 0; i < n; i ++ ) {
									_v.set( N[ i * 3 ], N[ i * 3 + 1 ], N[ i * 3 + 2 ] );
									const x = _v.x, y = _v.y, z = _v.z;
									_v.x = q[ 0 ] * x + q[ 3 ] * y + q[ 6 ] * z;
									_v.y = q[ 1 ] * x + q[ 4 ] * y + q[ 7 ] * z;
									_v.z = q[ 2 ] * x + q[ 5 ] * y + q[ 8 ] * z;
									_v.normalize();
									const o = ( vo + i ) * 3;
									nor[ o ] = _v.x; nor[ o + 1 ] = _v.y; nor[ o + 2 ] = _v.z;
								}
							}
							if ( U ) uv.set( U.subarray( 0, n * uvA.itemSize ), vo * uvA.itemSize );
							if ( X ) { for ( let j = 0; j < X.count; j ++ ) idx[ io + j ] = X.getX( j ) + vo; io += X.count; }
							vo += n;
							await tick();
						}
					}
					geo = new THREE.BufferGeometry();
					geo.setAttribute( 'position', new THREE.BufferAttribute( pos, 3 ) );
					if ( nor ) geo.setAttribute( 'normal', new THREE.BufferAttribute( nor, 3 ) );
					if ( uv ) geo.setAttribute( 'uv', new THREE.BufferAttribute( uv, uvA.itemSize, uvA.normalized ) );
					if ( idx ) geo.setIndex( new THREE.BufferAttribute( idx, 1 ) );
				}
				if ( ! geo ) { keepInst.add( mat ); continue; }
				geo.computeBoundingSphere();
				const mesh = new THREE.Mesh( geo, mat );
				mesh.name = 'furn_weld_' + mat.name;
				mesh.castShadow = mesh.receiveShadow = true;
				mesh.frustumCulled = false;
				out.add( mesh );
			}
			out.userData.keepInst = keepInst;
			// a sync weld got there first, or the level was let go meanwhile
			if ( weld || gone ) { for ( const m of out.children ) m.geometry.dispose(); return weld || out; }
			weld = out;
			group.add( weld );
			return weld;
		} )();
		return weldJob;
	}
	let isWeld = false;
	// a piece is drawn when it stands, and - on a walk - only if its material would not weld
	const vis = ( q ) => q.s > 0 && ( ! isWeld || weld.userData.keepInst.has( q.mesh.material ) );
	/* FURN_GRAPH: while the weld draws every piece, the thousands of hidden
	 * per-piece meshes leave the scene graph - three walks (and re-multiplies)
	 * every child of the graph on every render call, hidden or not. They are
	 * put back, first in the group as they were, the moment they are wanted.
	 * `?furngraph=old` keeps them in, as before. */
	const instIn = ( on ) => {
		if ( on === ( inst.parent === group ) ) return;
		if ( on ) { group.add( inst ); group.children.splice( group.children.indexOf( inst ), 1 ); group.children.unshift( inst ); }
		else inst.removeFromParent();
	};
	const instFit = () => { if ( ! FURN_GRAPH_OLD ) instIn( ! ( isWeld && weld.userData.keepInst.size === 0 ) ); };
	function useWeld( on ) {
		if ( on ) welded();
		if ( on === isWeld ) return false;
		isWeld = on;
		weld.visible = on;
		for ( const list of units.values() ) for ( const q of list ) q.mesh.visible = vis( q );
		instFit();
		return true;
	}
	// the stagger: by the reveal order, spread over FURN_SPREAD of the dial
	for ( const list of units.values() ) {
		list.sort( ( a, b ) => a.order - b.order || a.room - b.room );
		list.forEach( ( q, k ) => { q.d = list.length > 1 ? FURN_SPREAD * k / ( list.length - 1 ) : 0; } );
	}
	const _m = new THREE.Matrix4(), _s = new THREE.Vector3();
	const put = ( q, s ) => {
		if ( q.s === s ) return false;
		q.s = s;
		if ( s > 0 ) { q.mesh.matrix.copy( q.base ).scale( _s.setScalar( s ) ); q.mesh.matrixWorldNeedsUpdate = true; }
		q.mesh.visible = vis( q );
		return true;
	};
	const ease = ( t ) => t * t * ( 3 - 2 * t );
	return {
		group, heights, units, tris, pieces: [ ...units.values() ].reduce( ( a, l ) => a + l.length, 0 ),
		/* One flat's pieces at dial `amount`: each arrives over the last
		 * (1 - spread) of its own share, the first pieces first, and leaves
		 * the same way back. */
		reveal( token, amount ) {
			let moved = false;
			for ( const q of units.get( token ) || [] ) {
				const t = Math.max( 0, Math.min( 1, ( amount - q.d ) / ( 1 - FURN_SPREAD ) ) );
				moved = put( q, ease( t ) ) || moved;
			}
			return moved;
		},
		all( v ) {
			let moved = false;
			for ( const list of units.values() ) for ( const q of list ) moved = put( q, v ) || moved;
			return moved;
		},
		/* walking: every piece in place, welded; anything else: instanced */
		walk( on ) {
			const a = useWeld( !! on );
			const b = on ? this.all( 1 ) : false;
			return a || b;
		},
		welded,
		weldedAsync,
		get instanced() { return inst; },
		/* the pieces in the graph for a compile; call what it returns after */
		instHold() { if ( inst.parent === group ) return () => {}; instIn( true ); return instFit; },
		/* one mesh of each (geometry, material): what a compile has to see */
		reps,
		/* For the rigs: how many pieces of each flat are standing (scale > 0). */
		standing() {
			const out = {};
			// pieces, not primitives: a piece of several materials is several instances
			for ( const [ tok, list ] of units ) { const n = new Set( list.filter( q => q.s > 0 ).map( q => q.node ) ).size; if ( n ) out[ tok ] = n; }
			return { by: out, all: [ ...units.values() ].reduce( ( a, l ) => a + l.length, 0 ), weld: isWeld };
		},
		dispose() {
			gone = true;
			for ( const m of inst.children ) m.dispatchEvent( { type: 'dispose' } );
			for ( const S of sets.values() ) S.geo.dispose();
			if ( weld ) for ( const m of weld.children ) m.dispatchEvent( { type: 'dispose' } );
			if ( weld ) for ( const m of weld.children ) m.geometry.dispose();
		},
	};
}
const ZERO = new THREE.Matrix4().makeScale( 0, 0, 0 );

function findDoor( level, node ) {
	for ( const u of level.units || [] ) for ( const d of u.doors || [] ) if ( d.node === node ) return d;
	for ( const d of level.doors || [] ) if ( d.node === node ) return d;
	return null;
}

/* ----------------------------------------------------------- the drawing
 * The floor view's look, patched onto the INTERIOR'S OWN COPIES of the
 * materials (the street never draws an int_* and the lift's metal_dark is
 * copied too), so nothing here can touch the street:
 *
 *   walls, doors, frames, rails - ink
 *   a flat's floors             - the brand's amber (the hex that comes out
 *                                 as `--amber`, see app.js PLAN_AMBER)
 *   the common floors           - paper: the corridor, the halls, the stairs
 *   glass                       - gone
 *
 * ...and each flat's own dial `rev` (one float per flat in `LVU.rev`, looked
 * up by `aunit`) takes its walls and floors back to the materials as they are
 * modelled. `amt` is the drawing itself, `dim` the rest of the storey
 * standing back while one flat is open. Uniforms only: lighting a flat is a
 * float written, never a shader rebuilt. */
export const MAX_UNITS = 64;
export const LVU = {
	amt: uniform( 0 ),
	dim: uniform( 0 ),
	rev: uniformArray( new Array( MAX_UNITS ).fill( 0 ), 'float' ),
	paper: uniform( new THREE.Vector3( 0.80, 0.78, 0.74 ) ),
	seed: uniform( 0 ),
};
const LV_FLOOR = /^(int_parquet|int_tile_floor|int_tile_grey|int_tile_white|int_marble|int_stone_dark)$/;
const LV_GLAZE = /^(int_glass)$/;
export const classOf = ( name ) => LV_GLAZE.test( name ) ? 'glaze' : LV_FLOOR.test( name ) ? 'floor' : 'arch';

export function patchDrawing( m, tone ) {
	if ( ! m || m.__lv ) return;
	m.__lv = true;
	const cls = classOf( m.name );
	const au = attribute( 'aunit', 'float' );
	const rev = LVU.rev.element( int( au.add( 0.5 ) ) );
	const ink = LVU.amt.mul( oneMinus( smoothstep( 0.0, 0.55, rev ) ) );
	if ( cls === 'glaze' ) {
		/* Taken out of the drawing in one movement with the walls, by the
		 * stipple the x-ray uses, so it costs no transparent pass. */
		const p = screenCoordinate.xy;
		const g = p.x.mul( 0.06711056 ).add( p.y.mul( 0.00583715 ) ).add( LVU.seed ).fract()
			.mul( 52.9829189 ).fract().mul( 0.96 ).add( 0.02 );
		m.opacityNode = ( m.opacityNode || float( 1 ) ).mul( atLeast( g, oneMinus( ink ) ) );
		m.alphaTest = 0.5;
		return;
	}
	const own = atLeast( 0.5, au );                  // 1 inside a flat, 0 common
	const fl = mix( LVU.paper, tone.amber, own );
	const t = ( cls === 'arch' ? tone.ink : fl ).mul( oneMinus( LVU.dim ) );
	const c = m.colorNode || vec3( m.color.r, m.color.g, m.color.b );
	m.colorNode = mix( c, t.mul( tone.lit ), ink );
	const e = m.emissiveNode || vec3( 0.0 );
	m.emissiveNode = mix( e, t.mul( oneMinus( tone.lit ) )
		.mul( cls === 'arch' ? float( 1.0 ) : tone.gain ), ink );
	const r = m.roughnessNode || float( m.roughness ?? 0.9 );
	m.roughnessNode = mix( r, float( 0.97 ), ink );
	if ( m.metalnessNode || m.metalness )
		m.metalnessNode = mix( m.metalnessNode || float( m.metalness ), float( 0.0 ), ink );
}

/* ---------------------------------------------------------- the section
 * A plan is a SECTION: the walls cut at the plan's height and drawn solid.
 * The interiors are modelled full height and cut in the renderer by a
 * clipping plane, which leaves every cut wall OPEN at the top - a hollow box
 * you look down into, and through, to whatever is under it. So the cut is
 * capped: the walls a body cannot pass (plan_meta `nav.solid`, which the
 * build reads off its own meshes and which includes the street's outer
 * walls and sills) are laid flat, a hair over the cut, as one mesh. It is
 * what the drawing's ink IS, so it is ink whatever the hover is doing. */
export function capGeometry( level, frame, at ) {
	const pos = [], nor = [];
	const v = new THREE.Vector3();
	for ( const p of ( level.nav && level.nav.solid ) || [] ) {
		const outer = ringOf( p ).map( q => new THREE.Vector2( q[ 0 ], q[ 1 ] ) );
		if ( outer.length < 3 ) continue;
		const holes = ( p.holes || [] ).map( h => h.map( q => new THREE.Vector2( q[ 0 ], q[ 1 ] ) ) );
		let tris;
		try { tris = THREE.ShapeUtils.triangulateShape( outer, holes ); } catch ( e ) { continue; }
		const all = outer.concat( ...holes );
		for ( const t of tris ) {
			/* Wound so the face looks UP in the world whichever way round the
			 * plan's polygon was drawn: the frame is a mirror of the plan. */
			const a = all[ t[ 0 ] ], b = all[ t[ 1 ] ], c = all[ t[ 2 ] ];
			const pa = frame.world( a.x, a.y, at ), pb = frame.world( b.x, b.y, at ), pc = frame.world( c.x, c.y, at );
			const n = v.copy( pb ).sub( pa ).cross( pc.clone().sub( pa ) );
			const order = n.y >= 0 ? [ pa, pb, pc ] : [ pa, pc, pb ];
			for ( const q of order ) { pos.push( q.x, q.y, q.z ); nor.push( 0, 1, 0 ); }
		}
	}
	const g = new THREE.BufferGeometry();
	g.setAttribute( 'position', new THREE.Float32BufferAttribute( pos, 3 ) );
	g.setAttribute( 'normal', new THREE.Float32BufferAttribute( nor, 3 ) );
	g.computeBoundingSphere();
	return g;
}

/* The level's own extent in plan metres: every walkable and every solid
 * polygon, so the loggias and the outer walls are inside it. */
export function levelBox( level ) {
	const polys = [];
	const nav = level.nav || {};
	for ( const w of nav.walk || [] ) polys.push( w.poly || w );
	for ( const s of nav.solid || [] ) polys.push( s );
	for ( const u of level.units || [] ) { polys.push( u.poly ); for ( const l of u.loggias || [] ) polys.push( l ); }
	for ( const c of level.corridor || [] ) polys.push( c );
	return bboxOf( polys );
}

/* ------------------------------------------------------------- the bands
 * The street's storey map: for every level the facades rise through, one
 * quad per face line, 8 cm proud of it - the same quads hit testing and
 * lighting both use. In plan metres; app.js puts them in the world. */
export function bandQuads( meta ) {
	const out = [];
	const levels = ( meta.levels || [] ).filter( l => l.h > 0 );
	for ( const L of levels ) {
		for ( const f of meta.facades || [] ) {
			if ( L.z < f.z0 - 1e-3 || L.z + L.h > f.z1 + 1e-3 ) continue;
			out.push( { level: L.id, z: L.z, h: L.h, block: f.block, a: f.a, b: f.b, out: f.out } );
		}
	}
	return out;
}
