/* ===================================================================== *
 *  The sales page.
 *
 *  index.html carries the prose; this fills in every fact from
 *  content.js, builds the parts that are data rather than copy - the
 *  flat picker, the price cards, the calculator, the gallery - and
 *  wires the hero to the scene app.js is already running behind it.
 *
 *  app.js and this file never import each other. The scene announces
 *  what it is doing on window (`lp:ready`, `lp:scene`, `lp:mode`) and
 *  takes instructions through `window.LP`, so either one can be opened
 *  on its own: lab.html runs the scene with no page around it, and this
 *  page degrades to a plain site if WebGPU is missing.
 * ===================================================================== */

import { SITE, STATS, FLATS, TYPES, SHOW, ISSUES, flatByN, SHOW_BLOCKS } from './content.js';
import { applyLang, applyHead, applyTitleFont, startLang, keepLang, lang, t, tf }
	from './i18n.js';

const $ = ( s, r = document ) => r.querySelector( s );
const $$ = ( s, r = document ) => [ ...r.querySelectorAll( s ) ];
const el = ( tag, cls, html ) => {
	const n = document.createElement( tag );
	if ( cls ) n.className = cls;
	if ( html != null ) n.innerHTML = html;
	return n;
};
/* content.js wraps anything still a guess as { ph:true, v }. */
const isPh = ( x ) => !! ( x && typeof x === 'object' && x.ph );
const val = ( x ) => isPh( x ) ? x.v : x;
const money = ( n ) => SITE.currency + Math.round( n ).toLocaleString( 'en-US' );
const num = ( n ) => Number( n ).toLocaleString( 'en-US' );
/* an area as the plans print it: always one decimal (55.0, not 55) */
const m2 = ( v ) => Number( v ).toFixed( 1 );

/* ======================================================= the scene seams
 * Every question this page asks the 3D scene, one function each. The scene
 * is being rebuilt from the architect's plans; these are the only places
 * that know what it can answer, so a scene that offers none of the new
 * calls - or no scene at all - leaves a page that still works. See the
 * seam paragraph in blender/plans/CONTRACT.md.
 *
 *   SCENE.floorOf( detail )   which residential floor (1..9) an event is about
 *   SCENE.flatOf( detail )    which flat an event is about (by `n` / `poly`)
 *   SCENE.showFlat()          which flat the 3D tour is standing in
 *   SCENE.canOpenFlat()       can the scene open ANY flat by its number?
 *   SCENE.openFlat( f )       open flat f in 3D (true if it did)
 *   SCENE.openFloor( floor )  the floor view of floor 1..9
 *   SCENE.walkIn( k )         walk in at entrance k (1..3, 'podium')
 *   SCENE.walkFlat( f )       walk into flat f from its front door */
const LP = () => window.LP || null;
const FLOORS = SITE.floors;
const SCENE = {
	floorOf( d ) {
		if ( ! d ) return 0;
		const lv = /^L(\d\d)$/.exec( d.level || '' );
		if ( lv ) return clampFloor( + lv[ 1 ] - 1 );            // L02 is floor 1
		/* The old scene numbers its STOREYS, the podium terrace being 1, so
		 * its storey n is the inventory's floor n - 1. Kept only while that
		 * scene is the one on the page. */
		if ( d.floor ) return clampFloor( ( d.floor | 0 ) - 1 );
		return 0;
	},
	flatOf( d ) {
		if ( ! d ) return null;
		if ( d.n != null ) return flatByN( d.n );
		const m = /^L\d\d-u(.+)$/.exec( d.poly || '' );
		if ( m ) return flatByN( m[ 1 ] );
		/* The old scene says only "unit 0..7 of the modelled row", which is
		 * no flat in the real building: nothing is named rather than the
		 * wrong flat. */
		return null;
	},
	showFlat() {
		const lp = LP();
		const n = lp && lp.showFlat;
		return ( n != null && flatByN( n ) ) || flatByN( val( SHOW ) ) || FLATS[ FLATS.length - 1 ];
	},
	canOpenFlat() { const lp = LP(); return !! ( lp && typeof lp.openFlat === 'function' ); },
	openFlat( f ) {
		const lp = LP();
		if ( ! f || ! lp || typeof lp.openFlat !== 'function' ) return false;
		try { return !! lp.openFlat( f.n ); } catch ( e ) { console.warn( 'openFlat', e ); return false; }
	},
	/* On foot: from a street door (`k` 1..3, or 'podium' for the terrace
	 * stair), or into flat f from its own front door. */
	canWalk() { const lp = LP(); return !! ( lp && typeof lp.walk === 'function' ); },
	walkIn( k ) {
		const lp = LP();
		if ( ! lp || typeof lp.entrance !== 'function' ) return false;
		try { lp.entrance( k ); return true; } catch ( e ) { console.warn( 'entrance', e ); return false; }
	},
	walkFlat( f ) {
		const lp = LP();
		if ( ! f || ! lp || typeof lp.walk !== 'function' ) return false;
		try { lp.walk( { flat: f.n } ); return true; } catch ( e ) { console.warn( 'walk', e ); return false; }
	},
	openFloor( fl ) {
		const lp = LP();
		if ( ! lp ) return false;
		const level = 'L' + String( fl + 1 ).padStart( 2, '0' );
		if ( typeof lp.openLevel === 'function' ) return !! lp.openLevel( level );
		// the old scene: its storey is the floor + 1, and it has fewer of them
		if ( typeof lp.setScene === 'function' ) {
			lp.setScene( 2, Math.min( fl + 1, lp.topFloor || fl + 1 ), 'plan' );
			return true;
		}
		return false;
	},
};
function clampFloor( n ) { return n >= 1 && n <= FLOORS ? n : 0; }
window.LPpage = { SCENE, flatByN };        // for the rigs and the console

/* ------------------------------------------------------------- the facts
 * Every `data-v="key"` in the markup is filled from here, so a phone
 * number is written once and appears six times. ?ph=1 rings whatever is
 * still a guess. */
const FACTS = {
	...SITE,
	projectLine: `${ val( SITE.project ) } · ${ SITE.city }`,
	place: `${ val( SITE.district ) }, ${ SITE.city }`,
	floors: SITE.floors,
	flats: STATS.flats,
	// availability is not in the plans: a placeholder until the sales office's list
	available: { ph: true, v: STATS.available },
	parkingUnder: num( SITE.parkingUnder ),
	parkingOut: num( SITE.parkingOut ),
	commercialArea: num( Math.round( SITE.commercialArea ) ),
	officeArea: num( Math.round( SITE.officeArea ) ),
	get parkingLine() { return tf( 'Yes - {u} underground spaces on level -1, and {o} outdoor spaces around the building.',
		{ u: SITE.parkingUnder, o: SITE.parkingOut } ); },
	get banksLine() { return val( SITE.banks ).map( t ).join( ', ' ); },
	families: num( val( SITE.families ) ),
	get tourBadge() { const f = SCENE.showFlat(); return t( 'The show flat · ' ) + ( SHOW_BLOCKS ? tf( 'flat {n}, floor {f}, block {b}', { n: f.n, f: f.floor, b: f.block } ) : tf( 'flat {n}, floor {f}', { n: f.n, f: f.floor } ) ); },
	get tourTitle() { const f = SCENE.showFlat(); return tf( '{label}, {area} m²', { label: t( f.label ), area: f.areaTotal } ); },
	get tourFloor() { return SCENE.showFlat().floor; },
	get tourArea() { return SCENE.showFlat().areaTotal + ' m²'; },
	get tourPrice() { return { ph: true, v: money( SCENE.showFlat().price ) }; },
};

function fill() {
	if ( new URLSearchParams( location.search ).has( 'ph' ) ) document.body.classList.add( 'ph' );
	for ( const n of $$( '[data-v]' ) ) {
		const raw = FACTS[ n.dataset.v ];
		if ( raw === undefined ) continue;
		const v = val( raw );
		const how = n.dataset.href;
		if ( how === 'tel' ) n.href = 'tel:' + SITE.phoneHref;
		else if ( how === 'mailto' ) n.href = 'mailto:' + v;
		else if ( how === 'href' ) n.href = v;
		if ( ! how || how === 'tel' || how === 'mailto' ) n.textContent = t( v );
		if ( isPh( raw ) ) n.dataset.ph = '1';
	}
	$( '#year' ).textContent = new Date().getFullYear();
}

/* ---------------------------------------------------------------- header */
function header() {
	const head = $( '#head' ), hero = $( '#hero' );
	const onScroll = () => {
		head.classList.toggle( 'solid', scrollY > 24 );
		head.classList.toggle( 'onhero', scrollY < hero.offsetHeight - 120 );
	};
	addEventListener( 'scroll', onScroll, { passive: true } );
	onScroll();

	const burger = $( '.burger' );
	burger.addEventListener( 'click', () => {
		const open = document.body.classList.toggle( 'menu' );
		burger.setAttribute( 'aria-expanded', String( open ) );
	} );
	$$( '#nav a' ).forEach( a => a.addEventListener( 'click', () => {
		document.body.classList.remove( 'menu' );
		burger.setAttribute( 'aria-expanded', 'false' );
	} ) );
}

/* ------------------------------------------------------------- the scene
 * The hero is the only stretch of page the canvas shows through. Past it
 * the canvas is hidden outright rather than left to composite behind
 * opaque sections, and the scene - which only draws when something
 * changes it - is asked for a frame on the way back. */
function heroScene() {
	const stage = $( '#stage' ), hero = $( '#hero' );
	if ( 'IntersectionObserver' in window ) {
		new IntersectionObserver( ( es ) => {
			const on = es[ 0 ].isIntersecting;
			stage.classList.toggle( 'away', ! on );
			// past the hero the page owns the keyboard and the canvas is
			// not even composited; coming back, it is owed a frame
			if ( window.LP ) {
				window.LP.active = on;
				if ( on ) window.LP.invalidate( 24 );
			}
		}, { rootMargin: '10% 0px' } ).observe( hero );
	}

	// the filter band's own button: the controls are in the hero, the grid
	// they drive is further down
	$( '#seethem' ).addEventListener( 'click', ( e ) => {
		e.preventDefault();
		const sec = $( '#flats' );
		if ( sec ) sec.scrollIntoView( { behavior: 'smooth' } );
	} );

	const toHero = () => scrollTo( { top: 0, behavior: 'smooth' } );
	const openTour = ( flat ) => {
		if ( ! window.LP ) return;
		toHero();
		/* Scene 2 is TWO views - the storey from above and the flat itself -
		 * and testing only the scene number left a visitor who was already
		 * in the floor view exactly where they were, with the card under
		 * the hero quietly renamed. The floor view has to be asked to
		 * leave, and on the storey it is already standing on. */
		/* The real building: the tour opens THE flat, by its number. */
		if ( flat && SCENE.openFlat( flat ) ) { showTourFlat( flat ); return; }
		const plan = document.body.classList.contains( 'floorview' );
		if ( window.LP.scene !== 2 || plan )
			window.LP.setScene( 2, plan ? window.LP.floor : undefined );
		if ( flat ) showTourFlat( flat );
	};
	/* A link, so it is the type's own underline rather than a box - but the
	 * href is only there to make it one: the scene is switched here. */
	$( '#heroback' ).addEventListener( 'click', ( e ) => {
		e.preventDefault();
		if ( window.LP ) window.LP.setScene( 1 );
	} );
	window.openTour = openTour;

	addEventListener( 'lp:scene', ( e ) => {
		const two = e.detail.scene === 2;
		const plan = two && e.detail.view === 'plan';
		document.body.classList.toggle( 'scene2', two );
		document.body.classList.toggle( 'walkview', two && e.detail.view === 'walk' );
		document.body.classList.toggle( 'floorview', plan );
		if ( two ) showTourFlat( SCENE.flatOf( e.detail ) || SCENE.showFlat() );
		if ( plan ) fillTypeRail( SCENE.floorOf( e.detail ) );
		/* Told BEFORE the flight begins - `lp:scene` is announced at the top
		 * of setScene, the crane is aimed at the bottom of it - so the shot
		 * flies straight to the framing it will keep. */
		tellInset( plan );
	} );
	addEventListener( 'resize', () => tellInset( document.body.classList.contains( 'floorview' ) ) );

	/* ------------------------------------------- walking along the storey
	 * The floor view holds the plan at a scale it can be read at, so the
	 * far end of the row is off the right of the window. These two walk it
	 * along a flat at a time; the scene owns where the stops are and says
	 * which one it is on, and all the page does is push and grey out.
	 *
	 * The disabled state is driven by `lp:plan` rather than worked out
	 * here: how many stops there are depends on how much of the window the
	 * cards are covering, which is the scene's arithmetic, not ours. */
	const pager = $( '#planpager' );
	const pgPrev = $( '#plan-prev' ), pgNext = $( '#plan-next' );
	const stepBy = ( d ) => { if ( window.LP ) window.LP.planStepBy( d ); };
	pgPrev.addEventListener( 'click', () => stepBy( - 1 ) );
	pgNext.addEventListener( 'click', () => stepBy( 1 ) );
	addEventListener( 'lp:plan', ( e ) => {
		const { steps, atStart, atEnd } = e.detail;
		// one stop is no row to walk: the whole storey is already in frame
		pager.hidden = steps < 2;
		/* Placed here as well as from the frame: the arrows can be unhidden
		 * at any point in the view's life - how many stops there are
		 * depends on how much of the window the cards are covering - and
		 * one that is off the screen cannot be measured, so this is the
		 * first moment there is anything to place. */
		placePager( $( '#typerail' ) );
		/* On the ENDS rather than on the step index. The plan is dragged
		 * freely, so it comes to rest between two flats as often as on
		 * one, and an index cannot say whether there is any row left. */
		pgPrev.disabled = !! atStart;
		pgNext.disabled = !! atEnd;
	} );
	/* No keyboard shortcut for these. The obvious one is the arrow keys and
	 * they are taken: the fly controls strafe the camera on left and right
	 * everywhere the canvas is live, the floor view included, so binding
	 * them here would walk the camera and page the storey on one press. */

	// no WebGPU, no scene: the veil says so and the page carries on
	addEventListener( 'lp:ready', () => {
		$( '#hero' ).classList.add( 'live' );
		// the open flat's card can offer the 3D now that there is a scene to ask
		if ( openN ) openFlatCard( flatByN( openN ) );
	} );

	/* The scene lights the storey under the pointer and says which one it
	 * is; the page answers with what is for sale on it - the whole floor,
	 * both blocks, since the scene no longer has one street line to light. */
	const tag = $( '#floortag' );
	const onFloor = ( fl ) => FLATS.filter( f => f.floor === fl );

	/* The card rides the pointer. `lp:floor` only fires when the storey
	 * CHANGES - the scene has nothing to say while the pointer wanders
	 * across one floor - so the moving is this listener's job and the event
	 * only decides what the card says and whether it is there at all.
	 *
	 * Its size is measured once per change of text, not per move: reading
	 * offsetWidth on every pointermove is a forced layout on a frame that
	 * is already raycasting the facade. */
	const GAP = 18, EDGE = 12;
	let px = innerWidth / 2, py = innerHeight / 2, tw = 0, th = 0, on = false;

	function place() {
		if ( ! on ) return;
		// right and below the pointer, and flipped to the other side of it
		// when that would run the card off the window
		let x = px + GAP, y = py + GAP;
		if ( x + tw > innerWidth - EDGE ) x = px - GAP - tw;
		if ( y + th > innerHeight - EDGE ) y = py - GAP - th;
		x = Math.min( Math.max( EDGE, x ), Math.max( EDGE, innerWidth - EDGE - tw ) );
		y = Math.min( Math.max( EDGE, y ), Math.max( EDGE, innerHeight - EDGE - th ) );
		tag.style.transform = `translate3d(${ Math.round( x ) }px, ${ Math.round( y ) }px, 0)`;
	}

	function hide() { on = false; tag.hidden = true; }

	/* On the frame, not on the window: the pointer is only over a storey
	 * while it is over the canvas, and the canvas's own leave takes the
	 * card away with it. */
	$( '#frame' ).addEventListener( 'pointermove', ( e ) => {
		px = e.clientX; py = e.clientY;
		place();
	}, { passive: true } );
	$( '#frame' ).addEventListener( 'pointerleave', hide );

	/* A street door under the pointer: the card says which entrance, and
	 * that a click walks in. */
	let doorHot = null;
	addEventListener( 'lp:door', ( e ) => {
		doorHot = e.detail && e.detail.portal;
		if ( ! doorHot ) return hide();
		tag.innerHTML = `<b>${ e.detail.terrace ? t( 'Terrace stairs' ) : tf( 'Entrance {k}', { k: e.detail.k } ) }</b><span>${ t( 'Click to walk in' ) }</span>`;
		tag.hidden = false; on = true;
		tw = tag.offsetWidth; th = tag.offsetHeight;
		place();
	} );
	addEventListener( 'lp:floor', ( e ) => {
		if ( doorHot ) return;
		const n = SCENE.floorOf( e.detail );
		/* The office storey (L01) is a level of the real building too. */
		if ( ! n && e.detail && e.detail.level === 'L01' ) {
			tag.innerHTML = `<b>${ t( 'Offices' ) }</b><span>${ e.detail.offices || '' } · ${ num( Math.round( SITE.officeArea ) ) } m²</span>`;
			tag.hidden = false; on = true;
			tw = tag.offsetWidth; th = tag.offsetHeight;
			return place();
		}
		if ( ! n ) return hide();
		const sel = onFloor( n ), free = sel.filter( f => f.status === 'available' );
		tag.innerHTML = `<b>${ tf( 'Floor {n} of {all}', { n, all: FLOORS } ) }</b>` + ( free.length
			? `<span>${ tf( '{free} of {all} free', { free: free.length, all: sel.length } ) } · ${ t( 'from' ) } `
				+ `${ money( Math.min( ...free.map( f => f.price ) ) ) }</span>`
			: `<span>${ tf( '{n} flats · all taken', { n: sel.length } ) }</span>` );
		/* Shown, then measured, then placed - all in this one task, so the
		 * browser paints it once, already under the pointer. Measuring it
		 * while it is still `hidden` reads 0 off a `display:none` box and
		 * the card would flash in the top-left corner. */
		tag.hidden = false;
		on = true;
		tw = tag.offsetWidth; th = tag.offsetHeight;
		place();
	} );

	/* ------------------------------------------- the flats' own areas
	 * One badge per flat in the floor view, standing on the middle of its
	 * own plan. The scene owns WHERE: it projects the centre of each unit
	 * and says how far that flat has been furnished, and only speaks when
	 * one of the two has changed - a drag moves the plan sixty times a
	 * second and this is eight DOM writes every time it does.
	 *
	 * A badge names its flat's own total area when the scene says which flat
	 * it stands on (`n` / `poly`); the old scene does not, and every unit in
	 * its row is the modelled one, so there the badge is the show flat's. */
	const badgeBox = $( '#planbadges' );
	const badges = [];
	/* ...and the real building's: a whole level is up to 23 flats on one
	 * plate, so each badge carries the flat's own NUMBER beside its area and
	 * is drawn compact (`data-lv`). An office carries its number and the
	 * area the scene read off the plan; a flat the inventory does not know
	 * shows the scene's area rather than the show flat's. */
	const entBox = $( '#planents' );
	const ents = [];
	addEventListener( 'lp:planbadge', ( e ) => {
		const list = e.detail.badges || [];
		const lv = !! e.detail.level;
		while ( badges.length < list.length ) {
			const b = el( 'div', 'pbadge' );
			b.innerHTML = `<span class="pb"><em></em><b></b><i>m<sup>2</sup></i></span>`;
			badgeBox.append( b );
			badges.push( b );
		}
		for ( let i = 0; i < badges.length; i ++ ) {
			const p = list[ i ];
			const b = badges[ i ];
			if ( p ) {
				const f = SCENE.flatOf( p );
				const v = f ? m2( f.areaTotal ) : p.area != null ? m2( p.area ) : String( SCENE.showFlat().areaTotal );
				const bb = b.querySelector( 'b' );
				if ( bb.textContent !== v ) bb.textContent = v;
				const no = p.n != null ? String( p.n ) : p.office != null ? t( 'Office' ) + ' ' + p.office : '';
				const em = b.querySelector( 'em' );
				if ( em.textContent !== no ) em.textContent = no;
				b.toggleAttribute( 'data-lv', lv );
			}
			/* Off the floor view altogether: taken out of the layout, not
			 * faded - there is no plan left under them to step off. */
			if ( ! p ) { b.hidden = true; continue; }
			b.hidden = false;
			/* The position is written here and the fade is CSS's, which is
			 * why they sit on two elements: this one is rewritten on every
			 * frame of a drag and must not be eased. */
			b.style.transform = `translate3d(${ p.x }px, ${ p.y }px, 0) translate(-50%, -50%)`;
			b.toggleAttribute( 'data-off', ! p.on );
		}
		/* The three entrances, named at their cores: C1 is entrance 1. */
		const el2 = e.detail.entrances || [];
		if ( entBox ) {
			while ( ents.length < el2.length ) {
				const b = el( 'button', 'pent' );
				b.type = 'button';
				/* ...and each one is a way in: the visitor is walked up to
				 * that entrance's street door. */
				b.addEventListener( 'click', () => { if ( b.dataset.k ) SCENE.walkIn( b.dataset.k ); } );
				entBox.append( b );
				ents.push( b );
			}
			ents.forEach( ( b, i ) => {
				const p = el2[ i ];
				if ( ! p ) { b.hidden = true; return; }
				b.hidden = false;
				const txt = t( 'Entrance' ) + ' ' + p.k;
				if ( b.textContent !== txt ) b.textContent = txt;
				b.dataset.k = p.k;
				b.title = t( 'Walk in' );
				b.style.transform = `translate3d(${ p.x }px, ${ p.y }px, 0) translate(-50%, -50%)`;
				b.toggleAttribute( 'data-off', ! p.on );
			} );
		}
	} );

	/* ------------------------------------------------ the rooms in it
	 * The fourth step. Every room of the open flat carries a dot; the dot
	 * names its room under the pointer and walks the camera into it when
	 * it is clicked. The scene projects them and says what they are
	 * called - it owns the plan - and this draws them, which is what lets
	 * them be hovered, tabbed to and clicked like anything else on the
	 * page. They are REUSED, not rebuilt: a drag of the plan rewrites
	 * eight transforms a frame and a rebuild would throw away the hover
	 * the pointer is sitting on.
	 *
	 * The name is a plain string from the scene and goes in as text, not
	 * as markup: the room table lives in app.js and nothing on this side
	 * should be able to turn it into HTML. */
	const dotBox = $( '#roomdots' );
	const dots = [];
	addEventListener( 'lp:roomdot', ( e ) => {
		const list = e.detail.dots || [];
		dotBox.hidden = ! list.length;
		while ( dots.length < list.length ) {
			const i = dots.length;
			const b = el( 'button', 'rdot' );
			b.type = 'button';
			b.append( el( 'i' ), el( 'span' ) );
			b.addEventListener( 'click', () => {
				if ( window.LP && window.LP.roomTo ) window.LP.roomTo( i );
			} );
			dotBox.append( b );
			dots.push( b );
		}
		for ( let i = 0; i < dots.length; i ++ ) {
			const p = list[ i ], b = dots[ i ];
			if ( ! p ) { b.hidden = true; continue; }
			b.hidden = false;
			const lab = b.lastChild;
			const nm = ( lang() === 'ka' && p.ka ) ? p.ka : t( p.name );
			if ( lab.textContent !== nm ) {
				lab.textContent = nm;
				b.setAttribute( 'aria-label', t( 'Look inside the ' ) + nm.toLowerCase() );
			}
			/* Written straight on, never eased: this is rewritten on every
			 * frame of a drag and a transition here would lag the plan by
			 * a fifth of a second. The fade is on `opacity`, which is the
			 * only thing that changes in steps. */
			/* No -50% here: the button is a point and the dot and the name
			 * are hung off it, so a name opening does not shift the dot it
			 * belongs to. */
			b.style.transform = `translate3d(${ p.x }px, ${ p.y }px, 0)`;
			b.toggleAttribute( 'data-off', ! p.on );
			/* A name opens to the right of its dot, and off the right-hand
			 * third of the window it opens to the left instead - a flat is
			 * framed against the card on the left, so its party end is
			 * always near the edge of the glass and "Bedroom balcony" is
			 * wider than what is left of it. */
			b.toggleAttribute( 'data-flip', p.x > innerWidth * 0.62 );
		}
	} );

	/* ...and the bar that takes the plan's place once the camera is inside
	 * one of them: which room this is, the two either side of it, and the
	 * way back out to the flat. */
	const roomBar = $( '#roombar' );
	/* The keys, over the bar, the FIRST time a visitor is stood in a room
	 * and not again. Walking is the one thing about being in there that
	 * nothing on the screen can show, so it has to be said; saying it over
	 * every room would be a caption on a photograph of a living room. It
	 * fades itself out and is then taken out of the layout, so a dragged
	 * look never catches it. */
	const roomHint = $( '#roomhint' );
	let hintSaid = false, hintTimers = [];
	const hintOff = () => {
		hintTimers.forEach( clearTimeout );
		hintTimers = [];
		roomHint.hidden = true;
		roomHint.classList.remove( 'gone' );
	};
	addEventListener( 'lp:room', ( e ) => {
		const { room, name } = e.detail;
		const on = room >= 0;
		document.body.classList.toggle( 'roomview', on );
		roomBar.hidden = ! on;
		if ( on ) $( '#room-name' ).textContent = ( lang() === 'ka' && e.detail.ka ) ? e.detail.ka : t( name || '' );
		if ( ! on ) return hintOff();
		if ( hintSaid ) return;
		hintSaid = true;
		roomHint.hidden = false;
		roomHint.classList.remove( 'gone' );
		hintTimers.push( setTimeout( () => roomHint.classList.add( 'gone' ), 6500 ) );
		hintTimers.push( setTimeout( hintOff, 7600 ) );
	} );
	$( '#room-prev' ).addEventListener( 'click',
		() => window.LP && window.LP.roomBy && window.LP.roomBy( - 1 ) );
	$( '#room-next' ).addEventListener( 'click',
		() => window.LP && window.LP.roomBy && window.LP.roomBy( 1 ) );
	$( '#room-out' ).addEventListener( 'click',
		() => window.LP && window.LP.roomTo && window.LP.roomTo( null ) );

	/* ------------------------------------------------- on foot
	 * The scene says where the visitor is standing (`lp:walk`): the storey,
	 * the flat or office, the room - in Georgian off the plan's own room
	 * table - and, in a lift, the stops it offers. The page writes it, draws
	 * the stops as buttons, and hands the scene a canvas for the minimap. */
	const wh = $( '#walkhud' ), whHint = $( '#walkhint' );
	const whStops = $( '#wh-stops' ), whLift = $( '#wh-lift' );
	let whHinted = false, whStopsKey = '';
	const levelName = ( d ) => d.level === 'L00' ? t( 'Ground floor' )
		: d.level === 'L01' ? t( 'Offices' )
		: d.level === 'ROOF' ? t( 'Roof' )
		: d.floor ? tf( 'Floor {n} of {all}', { n: d.floor, all: d.floors || FLOORS } ) : d.level;
	const stopName = ( lv ) => lv === 'L00' ? t( 'Ground' ) : lv === 'L01' ? t( 'Offices' )
		: /^L\d\d$/.test( lv ) ? String( + lv.slice( 1 ) - 1 ) : lv;
	const SURF = { corridor: 'Corridor', hall: 'Entrance hall', stair: 'Stairs', half_landing: 'Stairs',
		lift: 'Lift', sill: 'Lift', terrace: 'Terrace', commercial: 'Commercial floor', street: 'Street',
		head: 'Stair head', door: 'Doorway', flat: 'Flat', loggia: 'Loggia' };
	let walkSaid = null;
	function walkHud( d ) {
		walkSaid = d;
		document.body.classList.toggle( 'walking', !! d.on );
		wh.hidden = ! d.on;
		if ( ! d.on ) { whHint.hidden = true; return; }
		$( '#wh-level' ).textContent = levelName( d );
		$( '#wh-flat' ).textContent = d.flat != null ? tf( 'Flat {n}', { n: d.flat } )
			: d.office != null ? tf( 'Office {n}', { n: d.office } ) : '';
		const r = d.room;
		$( '#wh-room' ).textContent = r ? ( ( lang() === 'ka' && r.ka ) ? r.ka : t( r.name || 'Room' ) )
			: t( SURF[ d.surface ] || '' );
		wh.toggleAttribute( 'data-wait', !! d.waiting );
		// a car: its stops, the one it is at greyed, and where it is going
		const L = d.lift;
		whLift.hidden = ! L;
		if ( L ) {
			const key = L.id + '|' + L.stops.join( ',' ) + '|' + L.at + '|' + L.to + '|' + L.riding + '|' + lang();
			if ( key !== whStopsKey ) {
				whStopsKey = key;
				whStops.innerHTML = '';
				for ( const lv of L.stops.slice().reverse() ) {
					const b = el( 'button', 'wstop' );
					b.type = 'button';
					b.textContent = stopName( lv );
					b.setAttribute( 'aria-label', lv === 'L00' ? t( 'Ground floor' ) : lv === 'L01' ? t( 'Offices' )
						: tf( 'Floor {n}', { n: + lv.slice( 1 ) - 1 } ) );
					b.disabled = L.riding || lv === L.at;
					if ( lv === L.to && L.riding ) b.setAttribute( 'data-to', '' );
					if ( lv === L.at && ! L.riding ) b.setAttribute( 'data-at', '' );
					b.addEventListener( 'click', () => { if ( window.LP && window.LP.liftGo ) window.LP.liftGo( lv ); } );
					whStops.append( b );
				}
			}
		} else whStopsKey = '';
		if ( ! whHinted ) {
			whHinted = true;
			whHint.hidden = false;
			setTimeout( () => whHint.classList.add( 'gone' ), 7000 );
			setTimeout( () => { whHint.hidden = true; whHint.classList.remove( 'gone' ); }, 8100 );
		}
	}
	addEventListener( 'lp:walk', ( e ) => walkHud( e.detail || { on: false } ) );
	// the language can change under a walk: say it again in the new one
	addEventListener( 'lp:lang', () => { if ( walkSaid ) { whStopsKey = ''; walkHud( walkSaid ); } } );
	$( '#wh-out' ).addEventListener( 'click', () => window.LP && window.LP.walkExit && window.LP.walkExit() );
	addEventListener( 'lp:ready', () => { if ( window.LP && 'walkMap' in window.LP ) window.LP.walkMap = $( '#wh-map' ); } );
	addEventListener( 'keydown', ( e ) => {
		if ( e.key !== 'Escape' || ! document.body.classList.contains( 'walking' ) || ! window.LP || ! window.LP.walkExit ) return;
		/* One step out - to the flat the visitor was standing in - and no
		 * further: the open flat's own Escape (below) must not also take it. */
		e.stopImmediatePropagation();
		window.LP.walkExit();
	} );
	/* The three entrances (and the terrace stair) on the hero. Delegated: the
	 * language switch rewrites the line they stand in (i18n works on whole
	 * elements), and listeners on the old links would go with them. */
	document.addEventListener( 'click', ( e ) => {
		const b = e.target.closest && e.target.closest( '[data-walkin]' );
		if ( ! b ) return;
		e.preventDefault();
		toHero();
		SCENE.walkIn( b.dataset.walkin );
	} );

	/* ------------------------------------------------- the open flat
	 * The third step. A click on the floor view opens the flat it lands
	 * on: the scene comes down onto that one unit with its furniture
	 * pinned up, and the left column stops offering the storey's four
	 * types and starts answering for the one flat that was chosen. The
	 * two are the same column on purpose - the plate fills the display
	 * here, and a panel beside the cards would be two panels over flats
	 * somebody might be looking at.
	 *
	 * The scene says only WHICH of the eight drawn units it is; which
	 * flat in the inventory that is, and everything printed about it, is
	 * the page's (`SCENE.flatOf`). It is answered synchronously, before the
	 * dolly is built, so the shot flies to the window the new card will
	 * leave rather than to the one the cards were leaving. */
	addEventListener( 'lp:planfocus', ( e ) => {
		const floor = SCENE.floorOf( e.detail );
		const f = SCENE.flatOf( e.detail );
		document.body.classList.toggle( 'flatview', !! f );
		if ( f ) fillFlatPanel( f );
		else if ( document.body.classList.contains( 'floorview' ) ) fillTypeRail( floor );
		/* The name on the building's corner is the FLOOR VIEW's and only
		 * that view's. It used to be rewritten to `Flat 62` here; inside
		 * the flat it was a title over the picture saying what the card
		 * beside it already says twice, so `tellInset` takes it off
		 * instead and the text never changes. */
		/* The column has changed width and the line its contents start on
		 * has moved, and both are numbers the shot is framed to. */
		tellInset( document.body.classList.contains( 'floorview' ) );
	} );

	/* The way out that needs no aim. Clicking off the plan closes the flat
	 * too - that is the scene's own click - but a visitor reading the card
	 * has their hand nowhere near the drawing. */
	addEventListener( 'keydown', ( e ) => {
		if ( e.key !== 'Escape' || ! document.body.classList.contains( 'flatview' ) ) return;
		if ( ! window.LP ) return;
		/* One step at a time, outermost last: from inside a room Escape
		 * means "out of this room", and only from the flat itself does it
		 * mean "out of this flat". */
		if ( window.LP.room >= 0 ) return window.LP.roomTo( null );
		if ( window.LP.planFocusTo ) window.LP.planFocusTo( null );
	} );

	/* Entering the flat shuts every storey at once without announcing it
	 * (`floorReset` in app.js), so the card has to be told by the scene
	 * switch instead - otherwise it hangs over the tour naming a floor
	 * nobody is hovering. */
	addEventListener( 'lp:scene', hide );
	addEventListener( 'blur', hide );
}

/* How much of the window's left edge the page is standing on, so the scene can
 * frame the storey in what is left: the block then starts where the cards end
 * instead of lying under them. Measured off the rail itself rather than
 * computed from the CSS, so one number cannot drift from the other.
 *
 * Zero below the rail's breakpoint - there the cards are a full-width block
 * over the top of the plate, not a column beside it, and insetting the camera
 * would leave the storey a sliver down one side. */
const RAIL_BP = 760;             // matches the media query in site.css
function tellInset( on ) {
	if ( ! window.LP || ! window.LP.setInset ) return;
	const rail = $( '#typerail' );
	const wide = innerWidth > RAIL_BP;
	const shut = document.body.classList.contains( 'flatview' );
	/* The gutter between the cards and the block. 18 px put the building
	 * right up against the cards - "its to near to cards now" - so it is a
	 * share of the window now rather than a hairline, and grows with it.
	 *
	 * A THIRD of it with one flat open. That gutter is there to keep the
	 * storey off four cards it would otherwise crowd; with one flat in the
	 * window it is just glass nobody is using, and the whole point of the
	 * third step is to be close. */
	let gutter = Math.round( Math.min( 130, Math.max( 48, innerWidth * 0.06 ) ) );
	if ( shut ) gutter = Math.max( 26, Math.round( gutter / 3 ) );
	const left = rail ? Math.round( rail.getBoundingClientRect().right ) + gutter : 0;
	window.LP.setInset( on && wide ? left : 0 );
	/* ...and the line the cards start on, which the scene lays the top edge
	 * of the storey against. The FIRST CARD, not the rail: the rail's own
	 * line of counts is type over the clear strip above the plan, and lining
	 * the plate up with it would put the plate back under the type.
	 * Measured, again, rather than added up from the CSS. */
	const card = rail && rail.querySelector( '.tcard, .fpanel' );
	if ( window.LP.setTop ) {
		let top = 0;
		if ( on && card && wide ) top = Math.round( card.getBoundingClientRect().top );
		/* Narrow, with a flat open, the line is the panel's BOTTOM instead.
		 * Here the panel lies across the window rather than beside it, and
		 * one flat's card is tall enough to cover the whole of a shot that
		 * has nowhere else to go - so the flat opens UNDER it. The storey's
		 * own view still gives 0 on this layout: its cards are short, the
		 * plate is the size of the window, and standing the plate under
		 * them would leave a sliver. */
		window.LP.setTop( top );
	}
	/* ...and how much of the FOOT, which only the open flat is framed
	 * against. On the narrow layout its card is docked to the bottom of
	 * the window - a column beside the flat is not a layout a phone has -
	 * so what the scene needs there is where the page BEGINS coming up
	 * from the foot. Zero on every wide layout: there the card is a column
	 * and the foot is clear. */
	if ( window.LP.setFoot ) {
		const head = rail && rail.querySelector( '.thead' );
		window.LP.setFoot( on && shut && ! wide && head
			? Math.max( 0, Math.round( innerHeight - head.getBoundingClientRect().top ) + 10 )
			: 0 );
	}
	// ...and not with a flat open: see `lp:planfocus`
	placeFloorLabel( on && wide && card && ! shut, left, rail );
	// after the label: the arrows go on the line it was just put on
	placePager( rail );
}

/* The view's name, written on the TOP CORNER OF THE BUILDING.
 *
 * `left` is the plate's own left edge - the same number the scene is framed
 * to, so the label cannot drift off the corner it names - and the line is
 * the one the storey's counts are on, over the cards. One line of small
 * caps across the two: the counts over the cards they count, the view's name
 * over the building. Hidden on the narrow layout, where the cards lie across
 * the top of the plate and there is no corner to write on - and hidden with
 * a flat open, where the picture is one flat and the card names it. */
function placeFloorLabel( show, left, rail ) {
	const lab = $( '#floorlabel' );
	if ( ! lab ) return;
	lab.hidden = ! show;
	if ( ! show ) return;
	const head = rail.querySelector( '.thead' );
	lab.style.left = left + 'px';
	lab.style.top = Math.round( head.getBoundingClientRect().top ) + 'px';
}

/* ...and the two arrows on the OTHER END of that same line, hard against the
 * page's right gutter - which is the header's gutter too, so they come down
 * directly under its button. The line is the counts' line again, read off
 * the rail rather than added up from the CSS, and the buttons are CENTRED on
 * it: they are twice the height of the small caps, and hung off the top of
 * the line they read as a second row rather than the end of this one.
 *
 * Off the screen there is nothing to measure and nothing to place - the view
 * may have gone, or the storey may fit the window whole and the arrows be
 * hidden - and `lp:plan` places them again the moment they come back. The
 * narrow layout has no rail line to use and keeps the CSS fallback, under
 * the header. */
function placePager( rail ) {
	const pg = $( '#planpager' );
	if ( ! pg || ! pg.offsetHeight ) return;
	const head = rail && rail.querySelector( '.thead' );
	if ( ! head || ! $( '#floorlabel' ) || $( '#floorlabel' ).hidden ) {
		pg.style.top = '';
		return;
	}
	const r = head.getBoundingClientRect();
	pg.style.top = Math.round( r.top + r.height / 2 - pg.offsetHeight / 2 ) + 'px';
}

/* ------------------------------------------------------------ the type rail
 * The four plans, down the left of the floor view. The scene has just put the
 * camera over one storey; this says what is standing on it, type by type, and
 * a card jumps to that type in the flat picker below.
 *
 * The counts are the STOREY's, not the building's: a card over floor 6 that
 * quotes how many of a type are left in the whole block is answering a
 * question nobody asked. The price is that storey's cheapest, for the same
 * reason - prices climb with the floor. A type with nothing left on this
 * storey still shows, greyed, or the rail would change shape floor to floor
 * and stop reading as the building's four plans. */
/* A flat card's block line - or, with the owner's switch off (content.js
 * SHOW_BLOCKS), its entrance alone. */
const blockRow = ( f ) => SHOW_BLOCKS
	? `<dt>${ t( 'Block' ) }</dt><dd>${ tf( 'Block {b} · entrance {e}', { b: f.block, e: f.entrance } ) }</dd>`
	: `<dt>${ t( 'Entrance' ) }</dt><dd>${ String( f.entrance ) }</dd>`;

function fillTypeRail( floor ) {
	const rail = $( '#typerail' );
	const on = floor ? FLATS.filter( f => f.floor === floor ) : [];
	/* The storey's counts, on the cards they count. The view's own name is
	 * not here: it is written on the top corner of the building instead
	 * (`#floorlabel`, placed in `tellInset`), on the same line as this one.
	 * The rail's top margin is what stands the cards down off the header, so
	 * the two labels share a line a good way down the window rather than
	 * both crowding the header. */
	const head = el( 'div', 'thead',
		`<a class="stepback" href="#top">${ t( '← Back to the street' ) }</a>`
		+ `<span><b>${ floor ? tf( 'Floor {n} of {all}', { n: floor, all: FLOORS } ) : t( 'Floor' ) }</b> · ${ tf( '{n} flats', { n: on.length } ) }</span>` );
	$( '.stepback', head ).addEventListener( 'click', ( e ) => {
		e.preventDefault();
		if ( window.LP ) window.LP.setScene( 1 );
	} );
	rail.replaceChildren( head );
	for ( const ty of TYPES ) {
		const mine = on.filter( f => f.type === ty.key );
		if ( ! mine.length ) continue;
		const free = mine.filter( f => f.status === 'available' );
		const lo = Math.min( ...mine.map( f => f.areaTotal ) ), hi = Math.max( ...mine.map( f => f.areaTotal ) );
		const area = lo !== hi ? `${ lo }–${ hi } m²` : `${ lo } m²`;
		const card = el( 'button', 'tcard',
			`<img alt="" loading="lazy" src="${ val( ty.plan ) }"${ isPh( ty.plan ) ? ' data-ph="1"' : '' }>`
			+ `<span><span class="n">${ t( ty.label ) }</span>`
			+ `<span class="m">${ area } · ${ tf( '{n} on this floor', { n: mine.length } ) }</span>`
			+ `<span class="p" data-ph="1">${ free.length
				? tf( 'from {price} · {n} free', { price: money( Math.min( ...free.map( f => f.price ) ) ), n: free.length } )
				: `<span class="gone">${ t( 'none left on this floor' ) }</span>` }</span></span>` );
		card.type = 'button';
		card.addEventListener( 'click', () => showType( ty, floor ) );
		rail.append( card );
	}
}

/* --------------------------------------------------------- the open flat
 * Which flat the scene has opened is `SCENE.flatOf` - by the flat's own
 * number, which the old "unit 0..7 of the modelled row" never was. */

/* The chosen flat's own card, in the column the four type cards were in.
 *
 * Everything a storey's card could not say: the number, the status, the
 * price for this flat rather than its type's cheapest, and the two things
 * to do about it. The head line above it keeps the shape the storey's
 * counts had - the scene lays the plate's top edge on the line below it,
 * so a different head would move the building. */
function fillFlatPanel( f ) {
	const rail = $( '#typerail' );
	const st = t( { available: 'Available', reserved: 'Reserved', sold: 'Sold' }[ f.status ] );
	/* The flat's own number - the architect's - not its place in a count. */
	const on = FLATS.filter( x => x.floor === f.floor ).length;
	const head = el( 'div', 'thead',
		`<a class="stepback" href="#top">${ t( '← The whole floor' ) }</a>`
		+ `<span><b>${ tf( 'Floor {n} of {all}', { n: f.floor, all: FLOORS } ) }</b> · ${ tf( 'flat {n}', { n: f.n } ) } · ${ tf( '{n} on this floor', { n: on } ) }</span>` );
	$( '.stepback', head ).addEventListener( 'click', ( e ) => {
		e.preventDefault();
		if ( window.LP && window.LP.planFocusTo ) window.LP.planFocusTo( null );
	} );
	rail.replaceChildren( head );
	const panel = el( 'div', 'fpanel',
		`<div class="fphead">
			<img alt="" loading="lazy" src="${ val( f.plan ) }"${ isPh( f.plan ) ? ' data-ph="1"' : '' }>
			<div>
				<span class="st st-${ f.status }" data-ph="1">${ st }</span>
				<span class="n">${ tf( 'Flat {n}', { n: f.n } ) } · ${ t( f.label ) }</span>
				<span class="sub">${ aspectText( f ) }</span>
				<span class="ar">${ m2( f.areaTotal ) }<i>m²</i></span>
			</div>
		</div>
		<dl>
			<dt>${ t( 'Floor' ) }</dt><dd>${ tf( '{n} of {all}', { n: f.floor, all: FLOORS } ) }</dd>
			${ blockRow( f ) }
			<dt>${ t( 'Area' ) }</dt><dd>${ tf( '{inner} + {balcony} m²', { inner: m2( f.area.inner ), balcony: m2( f.area.balcony ) } ) }</dd>
			<dt>${ t( 'Aspect' ) }</dt><dd>${ aspectText( f ) }</dd>
			<dt>${ t( 'Condition' ) }</dt><dd${ isPh( SITE.condition ) ? ' data-ph="1"' : '' }>${ t( val( SITE.condition ) ) }</dd>
		</dl>
		<div class="fpprice" data-ph="1"><b>${ money( f.price ) }</b><span>${ money( f.price / f.areaTotal ) } / m²</span></div>
		<div class="fpact">
			<button class="btn btn--amber btn--sm" type="button" data-go="book">${ f.status === 'sold'
				? t( 'Ask what else is free' ) : t( 'Book a viewing' ) }</button>
			${ SCENE.canWalk() ? `<button class="btn btn--ghost btn--sm" type="button" data-go="walk">${ t( 'Walk it' ) }</button>` : '' }
		</div>` );
	rail.append( panel );

	$( '[data-go="book"]', panel ).addEventListener( 'click', () => {
		bookFlat( f );
	} );
	// on foot, in at the flat's own front door
	const w = $( '[data-go="walk"]', panel );
	if ( w ) w.addEventListener( 'click', () => SCENE.walkFlat( f ) );
}

/* The enquiry, with this flat already chosen in it. Sold flats are not in
 * its list - there is nothing to book - so the field is left on "not
 * decided yet" rather than silently failing to select one nobody can have. */
function bookFlat( f ) {
	const sel = $( '#l-flat' );
	if ( sel ) sel.value = f && f.status !== 'sold' ? String( f.n ) : '';
	$( '#contacts' ).scrollIntoView( { behavior: 'smooth' } );
	setTimeout( () => $( '#l-name' ).focus(), 600 );
}

/* Which way a flat looks, in the page's language: the plan's compass
 * letters, joined the way each language joins a list. */
const SIDE_EN = { N: 'north', S: 'south', E: 'east', W: 'west' };
function aspectText( f ) {
	const w = [ ...( f.aspect || '' ) ].map( c => t( SIDE_EN[ c ] ) );
	if ( ! w.length ) return '–';
	const s = w.length === 1 ? w[ 0 ]
		: w.slice( 0, - 1 ).join( ', ' ) + t( ' and ' ) + w[ w.length - 1 ];
	return s.charAt( 0 ).toUpperCase() + s.slice( 1 );
}

/* A card is a way into the picker, not a dead tile: it sets the picker to
 * that type on this storey and scrolls to it, which is where a flat is
 * actually chosen.
 *
 * It drives the picker's OWN controls rather than its state. The filter and
 * its `apply` live inside the picker's builder, and a second copy of "what
 * the chips mean" out here is a copy that goes stale the first time the
 * picker changes. */
function showType( ty, floor ) {
	setFilter( { floor: floor ? String( floor ) : 'any', rooms: String( ty.rooms ) } );
	const sec = $( '#flats' );
	if ( sec ) sec.scrollIntoView( { behavior: 'smooth', block: 'start' } );
}

/* The card the hero shows once the camera is inside a flat: the flat the
 * scene says it is in (`SCENE.flatOf` on the event, else `SCENE.showFlat`). */
function showTourFlat( f ) {
	if ( ! f ) return;
	$( '[data-v="tourBadge"]' ).textContent = t( 'The show flat · ' )
		+ ( SHOW_BLOCKS ? tf( 'flat {n}, floor {f}, block {b}', { n: f.n, f: f.floor, b: f.block } ) : tf( 'flat {n}, floor {f}', { n: f.n, f: f.floor } ) );
	$( '[data-v="tourTitle"]' ).textContent = tf( '{label}, {area} m²', { label: t( f.label ), area: f.areaTotal } );
	$( '[data-v="tourFloor"]' ).textContent = f.floor;
	$( '[data-v="tourArea"]' ).textContent = f.areaTotal + ' m²';
	$( '[data-v="tourPrice"]' ).textContent = money( f.price );
}

/* -------------------------------------------------------------- location */
function walks() {
	const box = $( '#walks' );
	for ( const w of SITE.walks ) {
		const m = val( w.min );
		const n = el( 'div', 'cell walk',
			`<svg><use href="#i-${ w.icon }"/></svg><span class="n">${ w.label }</span>`
			+ `<span class="m"${ isPh( w.min ) ? ' data-ph="1"' : '' }>${ m } min</span>` );
		box.append( n );
	}
}

/* -------------------------------------------------------- the flat picker
 * One filter, two sets of controls. The band across the foot of the hero
 * (hidden for now, at the owner's word, but kept: "we will show it later")
 * has the bedroom chips, "floor from" and "price up to"; the #flats section
 * has block, entrance, floor, bedrooms and availability. Both write the
 * same `filter`, and `apply` redraws both - a chip pressed in one is
 * pressed in the other. */
const filter = { block: 'any', entrance: 'any', floor: 'any', rooms: 'any', status: 'any',
	floorFrom: 1, price: Infinity };

/* the section's chip rows, built from the data so they can never offer a
 * block, an entrance or a floor that does not exist */
function pickerChips() {
	const box = $( '#pickfilters' );
	if ( ! box ) return;
	const uniq = ( k ) => [ ...new Set( FLATS.map( f => f[ k ] ) ) ].sort( ( a, b ) => a > b ? 1 : - 1 );
	const row = ( key, label, opts ) => {
		const fld = el( 'div', 'fld' );
		fld.append( el( 'span', null, t( label ) ) );
		const chips = el( 'div', 'chips' );
		chips.setAttribute( 'role', 'group' );
		chips.setAttribute( 'aria-label', t( label ) );
		for ( const [ v, txt ] of opts ) {
			const c = el( 'button', 'chip', txt );
			c.type = 'button';
			c.dataset.f = key; c.dataset.v = String( v );
			chips.append( c );
		}
		fld.append( chips );
		box.append( fld );
	};
	box.replaceChildren();
	if ( SHOW_BLOCKS ) row( 'block', 'Block', [ [ 'any', t( 'Any' ) ], ...uniq( 'block' ).map( b => [ b, b ] ) ] );
	row( 'entrance', 'Entrance', [ [ 'any', t( 'Any' ) ], ...uniq( 'entrance' ).map( e => [ e, String( e ) ] ) ] );
	row( 'floor', 'Floor', [ [ 'any', t( 'Any' ) ], ...uniq( 'floor' ).map( n => [ n, String( n ) ] ) ] );
	row( 'rooms', 'Bedrooms', [ [ 'any', t( 'Any' ) ], ...TYPES.map( ty => [ ty.rooms, ty.rooms ? String( ty.rooms ) : t( 'Studio' ) ] ) ] );
	row( 'status', 'Show', [ [ 'any', t( 'All' ) ], [ 'available', t( 'Available' ) ] ] );
	applyTitleFont( box );
}

function setFilter( patch ) {
	Object.assign( filter, patch );
	apply();
}

function picker() {
	$$( '#f-rooms .chip' ).forEach( c => c.addEventListener( 'click', () => setFilter( { rooms: c.dataset.rooms } ) ) );

	const fFloor = $( '#f-floor' ), fPrice = $( '#f-price' );
	fFloor.min = '1';
	fFloor.max = String( FLOORS );
	fFloor.addEventListener( 'input', () => {
		$( '#o-floor' ).textContent = fFloor.value;
		setFilter( { floorFrom: + fFloor.value } );
	} );
	// the price slider spans the inventory's own prices (placeholders, like them)
	const lo = Math.floor( Math.min( ...FLATS.map( f => f.price ) ) / 5000 ) * 5000;
	const hi = Math.ceil( Math.max( ...FLATS.map( f => f.price ) ) / 5000 ) * 5000;
	fPrice.min = String( lo ); fPrice.max = String( hi ); fPrice.step = '1000'; fPrice.value = String( hi );
	fPrice.addEventListener( 'input', () => {
		const v = + fPrice.value;
		$( '#o-price' ).textContent = v >= + fPrice.max ? t( 'any' ) : money( v );
		setFilter( { price: v >= + fPrice.max ? Infinity : v } );
	} );

	pickerChips();
	const fbox = $( '#pickfilters' );
	if ( fbox ) fbox.addEventListener( 'click', ( e ) => {
		const c = e.target.closest( '.chip[data-f]' );
		if ( c ) setFilter( { [ c.dataset.f ]: c.dataset.v } );
	} );
	const list = $( '#flist' );
	if ( list ) list.addEventListener( 'click', ( e ) => {
		const r = e.target.closest( '[data-n]' );
		if ( r ) openFlatCard( flatByN( r.dataset.n ), true );
	} );
	apply();
}

/* The section's own rule. Availability is a chip here, where every status is
 * drawn in its colour; the hero band's count keeps the rule it always had -
 * only a flat that can actually be bought is counted. */
function passes( f, band = false ) {
	if ( filter.rooms !== 'any' && f.rooms !== + filter.rooms ) return false;
	if ( SHOW_BLOCKS && filter.block !== 'any' && f.block !== filter.block ) return false;
	if ( filter.entrance !== 'any' && f.entrance !== + filter.entrance ) return false;
	if ( filter.floor !== 'any' && f.floor !== + filter.floor ) return false;
	if ( f.floor < filter.floorFrom ) return false;
	if ( f.price > filter.price ) return false;
	if ( ( band || filter.status === 'available' ) && f.status !== 'available' ) return false;
	return true;
}

function apply() {
	const n = FLATS.filter( f => passes( f, true ) ).length;
	$( '#count' ).innerHTML = tf( n === 1 ? '<b>{n}</b> flat matches' : '<b>{n}</b> flats match', { n } );
	// both sets of chips show the one filter
	$$( '#f-rooms .chip' ).forEach( c => c.setAttribute( 'aria-pressed', String( c.dataset.rooms === String( filter.rooms ) ) ) );
	$$( '#pickfilters .chip[data-f]' ).forEach( c =>
		c.setAttribute( 'aria-pressed', String( String( filter[ c.dataset.f ] ) === c.dataset.v ) ) );
	drawList();
}

/* ------------------------------------------------------------ the list
 * Every flat that passes, in the architect's numbering, one hairline row
 * each: number, block and entrance, floor, type, total area, price, status.
 * The price and the status are placeholders (`data-ph`) - the plans do not
 * have them. */
const ST = { available: 'Available', reserved: 'Reserved', sold: 'Sold' };
let openN = null;
function drawList() {
	const list = $( '#flist' );
	if ( ! list ) return;
	const sel = FLATS.filter( f => passes( f ) );
	const out = [ `<div class="frow fhd" aria-hidden="true"><span>${ t( 'Flat' ) }</span><span>${ t( SHOW_BLOCKS ? 'Block' : 'Entrance' ) }</span>`
		+ `<span>${ t( 'Floor' ) }</span><span>${ t( 'Type' ) }</span><span>${ t( 'Area' ) }</span>`
		+ `<span>${ t( 'Price' ) }</span><span>${ t( 'Status' ) }</span></div>` ];
	for ( const f of sel ) {
		out.push( `<button type="button" class="frow st-${ f.status }${ f.n === openN ? ' on' : '' }" data-n="${ f.n }"`
			+ ` aria-label="${ tf( 'Flat {n}', { n: f.n } ) }">`
			+ `<b>${ f.n }</b>`
			+ `<span>${ SHOW_BLOCKS ? tf( '{b} · entr. {e}', { b: f.block, e: f.entrance } ) : String( f.entrance ) }</span>`
			+ `<span>${ f.floor }</span>`
			+ `<span>${ t( f.label ) }</span>`
			+ `<span class="ar">${ m2( f.areaTotal ) } m²</span>`
			+ `<span class="pr" data-ph="1">${ money( f.price ) }</span>`
			+ `<span class="st" data-ph="1"><i></i>${ t( ST[ f.status ] ) }</span></button>` );
	}
	if ( ! sel.length ) out.push( `<div class="fempty">${ t( 'No flats match these filters. Change the floor or price range — or let a manager find one for you. <br><a class="btn btn--amber" href="#contacts">Ask a manager</a>' ) }</div>` );
	list.innerHTML = out.join( '' );
	applyTitleFont( list );
	const c = $( '#pickcount' );
	if ( c ) c.innerHTML = tf( '<b>{n}</b> of {all} flats', { n: sel.length, all: FLATS.length } );
}

/* ------------------------------------------------------- one flat, in full
 * The aside beside the list. Its plan is drawn from the architect's own
 * drawing of THIS flat (web/flatplans.json, fetched the first time a flat
 * is opened), so it is true for every one of them; the furnished render of
 * the layout is added only where the flat IS that layout. */
let PLANS = null;
const plans = () => PLANS || ( PLANS = fetch( './flatplans.json' ).then( r => r.ok ? r.json() : {} ).catch( () => ( {} ) ) );

function planSvg( p ) {
	if ( ! p || ! p.o ) return '';
	const all = [ p.o, ...( p.b || [] ) ].flat();
	const xs = all.map( q => q[ 0 ] ), ys = all.map( q => q[ 1 ] );
	const x0 = Math.min( ...xs ) - 0.4, y0 = Math.min( ...ys ) - 0.4;
	const w = Math.max( ...xs ) + 0.4 - x0, h = Math.max( ...ys ) + 0.4 - y0;
	const d = ( pts ) => 'M' + pts.map( q => q[ 0 ].toFixed( 2 ) + ' ' + q[ 1 ].toFixed( 2 ) ).join( 'L' ) + 'Z';
	/* Drawn in the plan's own frame and turned so the street (+y, south) is at
	 * the foot - the way the architect's sheets read. */
	return `<svg class="fdplan" viewBox="${ x0.toFixed( 2 ) } ${ y0.toFixed( 2 ) } ${ w.toFixed( 2 ) } ${ h.toFixed( 2 ) }" role="img" aria-label="${ t( 'Plan of the flat' ) }">`
		+ `<path class="o" d="${ d( p.o ) }"/>`
		+ ( p.b || [] ).map( b => `<path class="b" d="${ d( b ) }"/>` ).join( '' )
		+ ( p.r || [] ).map( r => `<path class="r" d="${ d( r ) }"/>` ).join( '' )
		+ ( p.w || [] ).map( w => `<path class="w" d="M${ w[ 0 ][ 0 ] } ${ w[ 0 ][ 1 ] }L${ w[ 1 ][ 0 ] } ${ w[ 1 ][ 1 ] }"/>` ).join( '' )
		+ ( p.d ? `<path class="d" d="M${ p.d[ 0 ][ 0 ] } ${ p.d[ 0 ][ 1 ] }L${ p.d[ 1 ][ 0 ] } ${ p.d[ 1 ][ 1 ] }"/>` : '' )
		+ `</svg>`;
}

function openFlatCard( f, user = false ) {
	const box = $( '#fside' );
	if ( ! box || ! f ) return;
	openN = f.n;
	$$( '#flist .frow.on' ).forEach( r => r.classList.remove( 'on' ) );
	const row = $( `#flist .frow[data-n="${ CSS.escape( f.n ) }"]` );
	if ( row ) row.classList.add( 'on' );
	// a link to this flat is its own number
	if ( user ) history.replaceState( null, '', '#flat-' + f.n );
	const notes = ISSUES.filter( i => i.n === f.n );
	const img = isPh( f.plan ) ? '' : `<figure class="fdimg"><img alt="" loading="lazy" src="${ f.plan }">`
		+ `<figcaption>${ t( 'This layout, furnished' ) }</figcaption></figure>`;
	const in3d = SCENE.canOpenFlat()
		? `<button class="btn btn--ghost btn--sm" type="button" data-go="3d">${ t( 'See it in 3D' ) }</button>`
			+ ( SCENE.canWalk() ? `<button class="btn btn--ghost btn--sm" type="button" data-go="walk">${ t( 'Walk it' ) }</button>` : '' )
		: ( LP() ? `<button class="btn btn--ghost btn--sm" type="button" data-go="tour">${ t( 'Walk the show flat' ) }</button>` : '' );
	box.innerHTML = `<div class="fdetail" data-n="${ f.n }">
		<div class="fdtop"><span class="st st-${ f.status }" data-ph="1"><i></i>${ t( ST[ f.status ] ) }</span>
			<span class="fdno">${ tf( 'Flat {n}', { n: f.n } ) }</span></div>
		<h3>${ t( f.label ) }<span>${ aspectText( f ) }</span></h3>
		<div class="fdar">${ m2( f.areaTotal ) }<i>m²</i></div>
		<div class="fdplanbox" aria-busy="true"></div>
		<dl>
			${ blockRow( f ) }
			<dt>${ t( 'Floor' ) }</dt><dd>${ tf( '{n} of {all}', { n: f.floor, all: FLOORS } ) }</dd>
			<dt>${ t( 'Living area' ) }</dt><dd>${ m2( f.area.inner ) } m²</dd>
			<dt>${ t( f.outdoor.includes( 'loggia' ) && ! f.outdoor.includes( 'balcony' ) ? 'Loggia' : 'Balcony' ) }</dt><dd>${ m2( f.area.balcony ) } m²</dd>
			<dt>${ t( 'Total' ) }</dt><dd>${ m2( f.area.total ) } m²</dd>
			<dt>${ t( 'Bedrooms' ) }</dt><dd${ f.typeFrom === 'size' ? ' data-ph="1"' : '' }>${ f.rooms ? f.rooms : t( 'Studio' ) }</dd>
			<dt>${ t( 'Condition' ) }</dt><dd${ isPh( SITE.condition ) ? ' data-ph="1"' : '' }>${ t( val( SITE.condition ) ) }</dd>
		</dl>
		<div class="fdprice" data-ph="1"><b>${ money( f.price ) }</b><span>${ money( f.price / f.areaTotal ) } / m²</span></div>
		<div class="fdact">
			<button class="btn btn--amber btn--sm" type="button" data-go="book">${ f.status === 'sold' ? t( 'Ask what else is free' ) : t( 'Book a viewing' ) }</button>
			${ in3d }
		</div>
		${ img }
		${ notes.length ? `<ul class="fdnotes">${ notes.map( i => `<li>${ i.note || i.kind }</li>` ).join( '' ) }</ul>` : '' }
	</div>`;
	$( '[data-go="book"]', box ).addEventListener( 'click', () => bookFlat( f ) );
	const go3 = $( '[data-go="3d"]', box );
	if ( go3 ) go3.addEventListener( 'click', () => { if ( SCENE.openFlat( f ) ) scrollTo( { top: 0, behavior: 'smooth' } ); } );
	/* ...and on foot: the level opens and the visitor walks in at the flat's
	 * own front door. */
	const goW = $( '[data-go="walk"]', box );
	if ( goW ) goW.addEventListener( 'click', () => { if ( SCENE.walkFlat( f ) ) scrollTo( { top: 0, behavior: 'smooth' } ); } );
	const tour = $( '[data-go="tour"]', box );
	if ( tour ) tour.addEventListener( 'click', () => window.openTour && window.openTour( SCENE.showFlat() ) );
	plans().then( ( P ) => {
		const slot = $( `#fside .fdetail[data-n="${ CSS.escape( f.n ) }"] .fdplanbox` );
		if ( ! slot ) return;
		slot.removeAttribute( 'aria-busy' );
		slot.innerHTML = planSvg( P[ f.n ] );
	} );
	applyTitleFont( box );
	if ( user && innerWidth <= 900 ) box.scrollIntoView( { behavior: 'smooth', block: 'start' } );
}

/* `#flat-47-a` opens flat 47-a, on arrival and whenever the hash changes. */
function deepLink() {
	const go = ( scroll ) => {
		const m = /^#flat-(.+)$/.exec( decodeURIComponent( location.hash ) );
		const f = m && flatByN( m[ 1 ] );
		if ( ! f ) return;
		// a flat the current filter hides is still opened: the filter is cleared
		if ( ! passes( f ) ) setFilter( { block: 'any', entrance: 'any', floor: 'any', rooms: 'any', status: 'any', floorFrom: 1, price: Infinity } );
		openFlatCard( f );
		if ( scroll ) $( '#flats' ).scrollIntoView();
	};
	addEventListener( 'hashchange', () => go( true ) );
	go( true );
	if ( ! openN ) {
		// otherwise the aside starts on the flat the show flat stands for
		const f = SCENE.showFlat();
		if ( f ) openFlatCard( f );
	}
}

/* ------------------------------------------------------------ price cards */
function prices() {
	const box = $( '#pricecards' );
	// ...and again, every time the language changes: these are built, not
	// translated, so a switch rebuilds them and must not leave the old set
	// standing beside the new one
	box.replaceChildren();
	for ( const ty of STATS.from ) {
		const card = el( 'button', 'pcard',
			`<div class="ty">${ t( ty.label ) }</div>
			 <div class="pr" data-ph="1"><em>${ t( 'from' ) }</em>${ money( ty.from ) }</div>
			 <div class="ar">${ ty.area[ 0 ] }–${ ty.area[ 1 ] } m² · ${ tf( '{n} flats', { n: ty.count } ) }</div>
			 <div class="lf${ ty.left ? '' : ' none' }" data-ph="1">${ ty.left
				? tf( '{n} available now', { n: ty.left } )
				: t( 'None left — ask about the next release' ) }</div>` );
		card.type = 'button';
		card.addEventListener( 'click', () => {
			// the price card is a filter: pick the type and jump to the grid
			setFilter( { rooms: String( ty.rooms ) } );
			const sec = $( '#flats' );
			if ( sec ) sec.scrollIntoView( { behavior: 'smooth' } );
		} );
		box.append( card );
	}
	$( '#banklist' ).innerHTML = val( SITE.banks ).map( b => `<li>${ t( b ) }</li>` ).join( '' );
	$( '#partners' ).innerHTML = [ ...val( SITE.banks ), t( 'Licensed developer' ),
		t( 'Notary partner' ) ].map( b => `<span>${ b }</span>` ).join( '' );
}

/* ------------------------------------------------------------- calculator */
function calc() {
	const p = + $( '#c-price' ).value, d = + $( '#c-down' ).value, m = + $( '#c-term' ).value;
	const deposit = p * d / 100;
	const rest = p - deposit;
	$( '#c-price-v' ).textContent = money( p );
	$( '#c-down-v' ).textContent = `${ d }% · ${ money( deposit ) }`;
	$( '#c-term-v' ).textContent = tf( '{n} months', { n: m } );
	$( '#c-out' ).textContent = money( rest / m );
	$( '#c-note' ).textContent = tf( '{down} down, {rest} over {n} months.', { down: money( deposit ), rest: money( rest ), n: m } );
}
function calculator() {
	const c = $( '#c-price' );
	c.min = String( Math.floor( Math.min( ...FLATS.map( f => f.price ) ) / 1000 ) * 1000 );
	c.max = String( Math.ceil( Math.max( ...FLATS.map( f => f.price ) ) / 1000 ) * 1000 );
	c.value = String( SCENE.showFlat().price );
	$( '#c-down' ).value = String( val( SITE.downPct ) );
	$( '#c-term' ).value = String( val( SITE.months ) );
	[ '#c-price', '#c-down', '#c-term' ].forEach( s =>
		$( s ).addEventListener( 'input', calc ) );
	calc();
}

/* ---------------------------------------------------------------- gallery
 * Tiles start as captioned plates and become photographs the moment a
 * file of that name turns up in web/photos/, so the grid is never a row
 * of broken images while the photographer is still out. */
function gallery() {
	const tabs = $( '#gtabs' ), grid = $( '#ggrid' );
	tabs.replaceChildren();                 // same reason as `prices`
	const names = Object.keys( SITE.gallery );
	const draw = ( name ) => {
		grid.innerHTML = '';
		for ( const file of SITE.gallery[ name ] ) {
			const tile = el( 'div', 'shot plate',
				`<div><svg width="30" height="30"><use href="#i-cam"/></svg>
				 <div class="cap">${ t( name ) }</div><div class="nm">photos/${ file }</div></div>` );
			grid.append( tile );
			const img = new Image();
			img.alt = t( name ) + ' — ' + val( SITE.project );
			img.src = './photos/' + file;
			img.onload = () => {
				tile.className = 'shot';
				tile.innerHTML = '';
				tile.append( img );
				tile.addEventListener( 'click', () => {
					$( '#lightbox img' ).src = img.src;
					$( '#lightbox' ).classList.add( 'on' );
				} );
			};
		}
	};
	names.forEach( ( n, i ) => {
		const b = el( 'button', 'chip', t( n ) );
		b.type = 'button';
		b.setAttribute( 'aria-pressed', String( i === 0 ) );
		b.addEventListener( 'click', () => {
			$$( '#gtabs .chip' ).forEach( o => o.setAttribute( 'aria-pressed', String( o === b ) ) );
			draw( n );
		} );
		tabs.append( b );
	} );
	draw( names[ 0 ] );

	const lb = $( '#lightbox' );
	const close = () => lb.classList.remove( 'on' );
	lb.addEventListener( 'click', ( e ) => { if ( e.target !== $( '#lightbox img' ) ) close(); } );
	addEventListener( 'keydown', ( e ) => { if ( e.key === 'Escape' ) close(); } );
}

/* ----------------------------------------------------------------- form */
function formOptions() {
	const sel = $( '#l-flat' );
	const was = sel.value;
	sel.innerHTML = `<option value="">${ t( 'Not decided yet' ) }</option>`
		+ FLATS.filter( f => f.status !== 'sold' ).map( f =>
			`<option value="${ f.n }">${ tf( 'Flat {n} · {label} · {area} m² · {price}', { n: f.n, label: t( f.label ), area: f.areaTotal, price: money( f.price ) } ) }</option>`
		).join( '' );
	sel.value = was;
}

function form() {
	formOptions();
	const sel = $( '#l-flat' );
	const f = $( '#leadform' );
	const bad = ( id, msg ) => {
		$( '#' + id ).setAttribute( 'aria-invalid', String( !! msg ) );
		$( `.err[data-for="${ id }"]` ).textContent = msg || '';
		return ! msg;
	};
	f.addEventListener( 'submit', ( e ) => {
		e.preventDefault();
		const name = $( '#l-name' ).value.trim();
		const phone = $( '#l-phone' ).value.trim();
		const okName = bad( 'l-name', name.length < 2 ? t( 'Please tell us your name.' ) : '' );
		const okPhone = bad( 'l-phone',
			phone.replace( /\D/g, '' ).length < 9 ? t( 'A phone number we can call back on.' ) : '' );
		if ( ! okName || ! okPhone ) return;
		// There is no back end here: the enquiry is handed to whatever the
		// sales office uses. Point this at the CRM, a form endpoint or a
		// webhook and the rest of the page needs no change.
		console.info( 'enquiry', { name, phone, flat: sel.value || null } );
		f.classList.add( 'off' );
		$( '#done' ).classList.add( 'on' );
	} );
	[ 'l-name', 'l-phone' ].forEach( id =>
		$( '#' + id ).addEventListener( 'input', () => bad( id, '' ) ) );
}

/* ------------------------------------------------------- reveal on scroll */
function reveal() {
	if ( ! ( 'IntersectionObserver' in window )
		|| matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) {
		$$( '.rv' ).forEach( n => n.classList.add( 'in' ) );
		return;
	}
	const io = new IntersectionObserver( ( es ) => es.forEach( e => {
		if ( ! e.isIntersecting ) return;
		e.target.classList.add( 'in' );
		io.unobserve( e.target );
	} ), { rootMargin: '0px 0px -8% 0px', threshold: 0.06 } );
	$$( '.rv' ).forEach( n => io.observe( n ) );
}

/* The faint six-column rule the page is set against. It is drawn rather
 * than written into the markup, so a section opts in with `data-rules`. */
function rules() {
	for ( const sec of $$( '[data-rules]' ) ) {
		const w = $( '.wrap', sec );
		if ( ! w ) continue;
		const r = el( 'div', 'rules', '<i></i>'.repeat( 12 ) );
		w.prepend( r );
	}
}

/* ------------------------------------------------------------ language
 * The page is written in English and translated into Georgian, which is
 * what it opens in: this is a building in Rustavi and its buyers are
 * local. The order matters and is the whole of it - swap the prose, drop
 * the facts into wherever the Georgian put them, then take the capitals
 * up to Mtavruli, which only JavaScript can do.
 *
 * Everything the page builds for itself afterwards - the flat cards, the
 * counts, the price rows - goes through `t()` and is capped as it is
 * built, so there is no second pass over the document. */
function setLang( to, keep = true ) {
	const was = document.documentElement.dataset.lang;
	applyLang( to );
	applyHead( to );
	fill();
	applyTitleFont();
	$$( '#lang button' ).forEach( b =>
		b.setAttribute( 'aria-current', String( b.dataset.lang === to ) ) );
	if ( keep ) keepLang( to );
	// whatever the page drew for itself is in the other language now
	if ( was && was !== to ) { redraw(); applyTitleFont(); }
	// ...and the scene's own words the page writes (the walk's HUD)
	if ( was && was !== to ) dispatchEvent( new CustomEvent( 'lp:lang', { detail: { lang: to } } ) );
}

/* The parts that are data rather than copy. They are rebuilt rather than
 * translated in place: every one of them is a template with a number in
 * it, and a template is not a sentence you can look up. */
function redraw() {
	pickerChips();
	apply();
	if ( openN ) openFlatCard( flatByN( openN ) );
	formOptions();
	prices();
	calculator();
	gallery();
	if ( window.LP ) window.LP.invalidate( 8 );
}

function language() {
	$( '#lang' ).addEventListener( 'click', ( e ) => {
		const b = e.target.closest( 'button[data-lang]' );
		if ( b && b.dataset.lang !== document.documentElement.dataset.lang )
			setLang( b.dataset.lang );
	} );
	setLang( startLang(), false );
}

/* FIRST, before anything has written to the document. The dictionary is
 * keyed on index.html's own markup, and `fill()` stamps `data-ph="1"`
 * onto every fact that is still a guess - which changes that markup, so a
 * key captured afterwards would never match again. The English is taken
 * pristine here and kept, and everything below is free to rewrite it. */
language();
fill();
rules();
header();
heroScene();
walks();
picker();
prices();
calculator();
gallery();
form();
deepLink();
reveal();
// ...and the capitals over the parts the page has just built for itself
applyTitleFont();
