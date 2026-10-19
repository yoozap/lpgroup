/* ===================================================================== *
 *  Everything on the sales page that is a fact rather than a layout.
 *
 *  This is the only file that has to be edited to put the real project
 *  on the page: names, numbers, distances, prices and the inventory.
 *  index.html carries the prose; anything written `data-v="key"` there
 *  is filled from SITE below, so a phone number lives in one place and
 *  appears in six.
 *
 *  Values that were not known when the page was built are marked
 *  `ph( ... )`. They render normally, so the page always looks finished,
 *  but ?ph=1 in the address bar rings every one of them in amber - a
 *  checklist of what is still a guess. Replace the value and drop the
 *  `ph(` wrapper.
 * ===================================================================== */

let PH = 0;
const ph = ( v ) => { PH ++; return { ph: true, v }; };          // "still a guess"
export const placeholders = () => PH;

export const SITE = {

	/* ---------------------------------------------------------- identity */
	brand: 'LP Group',
	brandKa: 'ელპი ჯგუფი',
	project: ph( 'Todria 11' ),
	district: ph( 'Todria' ),
	city: 'Rustavi',
	landmark: ph( 'Tbilisi' ),
	landmarkMin: ph( 25 ),

	/* ---------------------------------------------------------- contact */
	phone: '+995 591 70 04 00',
	phoneHref: '+995591700400',
	email: ph( 'sales@lpgroup.ge' ),
	address: 'Todria St. 11, Rustavi',
	hours: ph( 'Mon–Sat, 10:00–19:00' ),
	facebook: ph( 'https://facebook.com/' ),
	mapUrl: ph( 'https://www.google.com/maps/search/?api=1&query=Rustavi+Todria+11' ),
	callbackMinutes: 15,

	/* ------------------------------------------------------ key numbers */
	/* The building in the hero is the one that was solved from the
	 * photograph: 36.05 m to the parapet at a 3.0 m floor-to-floor, which
	 * is where `floors` comes from. `flats` is derived from the inventory
	 * below rather than typed, so the two can never disagree. */
	floors: 12,
	built: '100%',
	keys: 'Right after purchase',

	/* ------------------------------------------------------- the fabric */
	frame: ph( 'Monolithic reinforced-concrete frame' ),
	insulation: ph( '100 mm mineral-wool facade insulation' ),
	windows: ph( 'REHAU double-glazed windows' ),
	lifts: ph( 'Şahin' ),
	balconyLine: ph( 'a balcony in every flat' ),
	condition: ph( 'white frame' ),
	conditionLong: ph( 'White frame: plastered walls, screed floors, wiring and plumbing brought to every room, '
		+ 'glazed windows and a steel entrance door. Ready for your own finish.' ),
	parkingLine: ph( 'Yes - underground, 48 spaces, sold separately.' ),
	shopsLine: ph( 'Pharmacy and a grocery' ),

	/* --------------------------------------------------------- location */
	walks: [
		{ icon: 'school', label: 'School', min: ph( 4 ) },
		{ icon: 'kinder', label: 'Kindergarten', min: ph( 3 ) },
		{ icon: 'bus', label: 'Bus stop', min: ph( 2 ) },
		{ icon: 'cart', label: 'Supermarket', min: ph( 3 ) },
		{ icon: 'park', label: 'Park', min: ph( 7 ) },
		{ icon: 'clinic', label: 'Clinic', min: ph( 6 ) },
	],

	/* ---------------------------------------------------------- payment */
	currency: '$',
	discountFull: ph( 5 ),              // % off for payment in full
	downPct: ph( 30 ),                  // developer instalment: deposit
	months: ph( 24 ),                   // ... over this many months
	interest: '0%',
	banks: ph( [ 'TBC Bank', 'Bank of Georgia', 'Liberty Bank' ] ),

	/* -------------------------------------------------------- developer */
	years: ph( 14 ),
	delivered: ph( 9 ),
	families: ph( 1200 ),

	/* ---------------------------------------------------------- gallery */
	/* Drop files into web/photos/ and name them here. Anything missing
	 * draws a captioned plate instead, so the grid never breaks. */
	gallery: {
		Facade: [ 'facade-1.jpg', 'facade-2.jpg', 'facade-3.jpg' ],
		Lobby: [ 'lobby-1.jpg', 'lobby-2.jpg' ],
		Courtyard: [ 'courtyard-1.jpg', 'courtyard-2.jpg' ],
		Flats: [ 'flat-1.jpg', 'flat-2.jpg', 'flat-3.jpg' ],
		Views: [ 'view-1.jpg', 'view-2.jpg' ],
		Video: [ 'drone.jpg' ],
	},
};

/* ===================================================================== *
 *  The inventory
 *
 *  Six flats to a floor over twelve floors: the four the facade's bay
 *  rhythm puts along the street, and two in the forward wing. Sizes and
 *  prices are seeded off the flat's own number, so the list is the same
 *  on every reload and a link to a flat still points at that flat.
 * ===================================================================== */

const PER_FLOOR = 6;

/* a plain 32-bit hash, used as the seed - same flat, same numbers */
const seed = ( n ) => { let h = ( n * 2654435761 ) >>> 0; h ^= h >>> 15; h = ( h * 2246822519 ) >>> 0; h ^= h >>> 13; return h >>> 0; };
const rnd = ( s, i ) => ( ( ( seed( s * 97 + i * 31 ) ) % 10000 ) / 10000 );

/* `plan` is the sales render of the type, cropped out of the developer's own
 * poster and keyed off its background (web/types/*.webp). Two of the four are
 * the real thing: `two` is the 88.4 m2 two-balcony plan - the one the 3D show
 * flat was modelled from - and `one` is the 52.2 m2 one-bedroom. The studio
 * and the three-bedroom have no render yet, so they borrow the nearest and
 * are marked `ph`: they look finished, and ?ph=1 rings them amber. Drop a
 * real `studio.webp` / `three.webp` in and unwrap the `ph(`. */
export const TYPES = [
	{ key: 'studio', rooms: 0, label: 'Studio', area: [ 38.4, 44.8 ], rate: 905,
		plan: ph( './types/one.webp' ) },
	{ key: 'one', rooms: 1, label: '1-bedroom', area: [ 51.6, 58.2 ], rate: 880,
		plan: './types/one.webp' },
	{ key: 'two', rooms: 2, label: '2-bedroom', area: [ 71.9, 81.4 ], rate: 835,
		plan: './types/two.webp' },
	{ key: 'three', rooms: 3, label: '3-bedroom', area: [ 94.6, 112.0 ], rate: 800,
		plan: ph( './types/two.webp' ) },
];
/* which type sits in each of the six positions on a floor */
const LINE = [ 'two', 'one', 'studio', 'two', 'three', 'one' ];
const ASPECT = [ 'Street, south-west', 'Street, south', 'Courtyard, east',
	'Street corner, south-west', 'Corner, west', 'Courtyard, north-east' ];

export const FLATS = ( () => {
	const out = [];
	for ( let fl = 1; fl <= SITE.floors; fl ++ ) {
		for ( let i = 0; i < PER_FLOOR; i ++ ) {
			const n = fl * 10 + ( i + 1 );
			const t = TYPES.find( t => t.key === LINE[ i ] );
			const r = rnd( n, 1 );
			// area walks across the type's range, rounded to the tenth
			const area = Math.round( ( t.area[ 0 ] + r * ( t.area[ 1 ] - t.area[ 0 ] ) ) * 10 ) / 10;
			// a flat is worth more the higher it stands, and the top two
			// floors carry the view premium the sales office actually charges
			const lift = 1 + ( fl - 1 ) * 0.0075 + ( fl >= SITE.floors - 1 ? 0.03 : 0 );
			const price = Math.round( area * t.rate * lift / 100 ) * 100;
			// 72 flats, most of them gone: the ones left are the story
			const s = rnd( n, 2 );
			const status = s > 0.80 ? 'available' : s > 0.72 ? 'reserved' : 'sold';
			out.push( {
				n, floor: fl, type: t.key, rooms: t.rooms, label: t.label,
				area, price, status,
				aspect: ASPECT[ i ],
				balcony: i !== 2,
				// the unit the 3D tour actually opens: top floor, on the corner
				tour: ( fl === SITE.floors && i === 3 ),
			} );
		}
	}
	// The flat the 3D tour opens is a real one: the corner unit the sales
	// office advertises at 77.7 m2. It is pinned here rather than seeded, so
	// the page and the brochure quote the same number.
	const tour = out.find( f => f.tour );
	tour.area = 77.7;
	tour.price = Math.round( tour.area * 835 * ( 1 + ( SITE.floors - 1 ) * 0.0075 + 0.03 ) / 100 ) * 100;
	return out;
} )();

/* the page quotes these rather than carrying its own copies */
export const STATS = {
	flats: FLATS.length,
	available: FLATS.filter( f => f.status === 'available' ).length,
	from: TYPES.map( t => ( {
		...t,
		from: Math.min( ...FLATS.filter( f => f.type === t.key && f.status !== 'sold' ).map( f => f.price ) ),
		left: FLATS.filter( f => f.type === t.key && f.status === 'available' ).length,
	} ) ),
};
