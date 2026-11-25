#!/usr/bin/env node
/* Every level of the real building, opened and checked against the plans.
 *
 *   node tools/levelcheck.cjs [outdir] [lang]
 *
 * For every level L01..L10: open it through the page's own API, wait for the
 * floor view to settle, shoot it, and assert
 *   - the scene sent one badge per unit of that level in plan_meta.json
 *   - every flat's badge names a flat of flats.js ON THAT LEVEL, and its
 *     area as the page drew it is that flat's total area in flats.js
 *   - the page drew exactly those badges (DOM), with those numbers.
 * Then three flats are opened - one per core, one of them a split "-a"
 * flat - and their rooms checked: one dot per plan_meta room.
 * Exit 1 on any mismatch. `BREAK=1` drops one badge in the check itself, to
 * prove the rig can fail.                                                 */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const ROOT = path.join( __dirname, '..' );
const OUT = process.argv[ 2 ] || path.join( ROOT, 'perf-shots', 'levelcheck' );
const LANG = process.argv[ 3 ] || 'en';
const BREAK = process.env.BREAK === '1';

const flatsSrc = fs.readFileSync( path.join( ROOT, 'web', 'flats.js' ), 'utf8' );
const FLATS = JSON.parse( /export const FLATS = (\[[\s\S]*?\]);\n/.exec( flatsSrc )[ 1 ] );
const PM = JSON.parse( fs.readFileSync( path.join( ROOT, 'web', 'plan_meta.json' ), 'utf8' ) );
const IX = JSON.parse( fs.readFileSync( path.join( ROOT, 'web', 'interior', 'furn', 'index.json' ), 'utf8' ) );
const m2 = ( v ) => Number( v ).toFixed( 1 );

( async () => {
	fs.mkdirSync( OUT, { recursive: true } );
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1600,900', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-levelcheck' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: 1600, height: 900, deviceScaleFactor: 1 } );
	const bad = [], cons = [];
	p.on( 'console', m => { const t = m.text();
		if ( ( m.type() === 'error' || /unmapped|invalid|failed/i.test( t ) ) && ! /404/.test( t ) ) cons.push( t.slice( 0, 200 ) ); } );
	p.on( 'pageerror', e => cons.push( 'PAGEERROR ' + String( e ).slice( 0, 200 ) ) );
	await p.evaluateOnNewDocument( () => { window.__ev = {};
		for ( const k of [ 'planbadge', 'planfocus', 'roomdot', 'scene' ] )
			addEventListener( 'lp:' + k, ( e ) => { window.__ev[ k ] = e.detail; } ); } );
	await p.goto( 'http://127.0.0.1:8777/index.html?lang=' + LANG, { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')", { timeout: 180000, polling: 100 } );
	await sleep( 2500 );
	const settle = async ( pred, ms = 20000 ) => {
		const t0 = Date.now();
		while ( Date.now() - t0 < ms ) { if ( await p.evaluate( pred ) ) return true; await sleep( 200 ); }
		return false;
	};

	for ( const L of PM.levels.filter( l => /^L(0[1-9]|10)$/.test( l.id ) ) ) {
		const units = ( L.flats || [] ).concat( L.offices || [] );
		await p.evaluate( ( id ) => window.LP.openLevel( id ), L.id );
		const ok = await settle( `window.__lv().open === '${ L.id }' && window.LP.scene === 2 && window.__lv().amt === 1 && window.__lv().tweens === 0` );
		if ( ! ok ) { bad.push( L.id + ': never settled' ); continue; }
		await sleep( 900 );
		await p.screenshot( { path: path.join( OUT, 'level_' + L.id + '.png' ) } );
		const got = await p.evaluate( () => ( {
			ev: ( window.__ev.planbadge || {} ).badges || [],
			dom: [ ...document.querySelectorAll( '#planbadges .pbadge' ) ].filter( b => ! b.hidden )
				.map( b => [ b.querySelector( 'em' ).textContent, b.querySelector( 'b' ).textContent ] ),
		} ) );
		const ev = BREAK ? got.ev.slice( 1 ) : got.ev;
		const errs = [];
		if ( ev.length !== units.length ) errs.push( `badges ${ ev.length } != units ${ units.length }` );
		if ( got.dom.length !== units.length ) errs.push( `page drew ${ got.dom.length } badges` );
		for ( const f of L.flats || [] ) {
			const rec = FLATS.find( x => x.n === f.n );
			const bdg = ev.find( x => x.n === f.n );
			const dom = got.dom.find( x => x[ 0 ] === f.n );
			if ( ! rec ) { errs.push( `flat ${ f.n } not in flats.js` ); continue; }
			if ( rec.level !== L.id ) errs.push( `flat ${ f.n } is ${ rec.level } in flats.js` );
			if ( ! bdg ) errs.push( `no badge for ${ f.n }` );
			if ( ! dom ) errs.push( `page drew no badge numbered ${ f.n }` );
			else if ( dom[ 1 ] !== m2( rec.area.total ) ) errs.push( `badge ${ f.n } reads ${ dom[ 1 ] }, flats.js total ${ m2( rec.area.total ) }` );
		}
		const flatsHere = FLATS.filter( f => f.level === L.id ).length;
		if ( flatsHere !== ( L.flats || [] ).length ) errs.push( `flats.js has ${ flatsHere } on ${ L.id }, plan_meta ${ ( L.flats || [] ).length }` );
		console.log( `${ L.id }  units ${ String( units.length ).padStart( 2 ) }  badges ${ String( ev.length ).padStart( 2 ) }  drawn ${ String( got.dom.length ).padStart( 2 ) }   ${ errs.length ? 'FAIL ' + errs.slice( 0, 4 ).join( '; ' ) : 'ok' }` );
		for ( const e of errs ) bad.push( L.id + ': ' + e );
	}

	/* One flat per core, one of them split ("-a"). */
	const pick = [ FLATS.find( f => f.core === 'C1' && /^\d+$/.test( f.n ) && f.floor === 3 ),
		FLATS.find( f => f.core === 'C2' && /-a$/.test( f.n ) ) || FLATS.find( f => /-a$/.test( f.n ) ),
		FLATS.find( f => f.core === 'C3' && f.floor === 7 ) ].filter( Boolean );
	for ( const f of pick ) {
		await p.evaluate( ( n ) => window.LP.openFlat( n ), f.n );
		const ok = await settle( `window.__lv().focus === '${ f.n }' && window.__lv().tweens === 0` );
		await sleep( 1500 );
		await p.screenshot( { path: path.join( OUT, 'flat_' + f.n + '.png' ) } );
		const got = await p.evaluate( () => ( { focus: window.__ev.planfocus, dots: ( window.__ev.roomdot || {} ).dots || [],
			card: ( document.querySelector( '#typerail .fpanel .n' ) || {} ).textContent || '' } ) );
		const pmf = PM.levels.find( l => l.id === f.level ).flats.find( x => x.n === f.n );
		const errs = [];
		/* The owner's rule for the floor view (memory floor-view-drawing):
		 * only the open flat is furnished - every piece the architect drew in
		 * it standing, and not one piece of any other flat. */
		const want = ( ( IX.levels[ f.level ] || {} ).units || {} )[ f.n ];
		if ( want ) {
			await settle( `( window.__bw.parts().find( q => q.name === '${ f.level }' ) || {} ).furn === 'in'`, 30000 );
			await sleep( 1800 );
			const st = await p.evaluate( ( lv ) => ( window.__bw.parts().find( q => q.name === lv ) || {} ).standing, f.level );
			const by = ( st && st.by ) || {}, tok = want.token || 'u' + f.n;
			const n = want.pieces.length, mine = by[ tok ] || 0;
			const others = Object.entries( by ).filter( ( [ k ] ) => k !== tok );
			if ( BREAK ) others.push( [ 'u?', 1 ] );
			console.log( `   furniture of ${ f.n }: ${ mine } of ${ n } pieces standing, ${ others.length } other flats furnished${ st && st.weld ? ' (WELDED - walk mode)' : '' }` );
			if ( mine !== n ) errs.push( `${ mine } of ${ n } pieces of its furniture standing` );
			if ( others.length ) errs.push( `other flats furnished too: ${ others.map( o => o[ 0 ] ).join( ',' ) }` );
		}
		if ( ! ok ) errs.push( 'never opened' );
		if ( ! got.focus || got.focus.n !== f.n ) errs.push( 'lp:planfocus did not name it' );
		if ( got.dots.length !== pmf.rooms.length ) errs.push( `${ got.dots.length } room dots, plan_meta ${ pmf.rooms.length } rooms` );
		if ( ! got.card.includes( f.n ) ) errs.push( `the page's card reads "${ got.card }"` );
		console.log( `flat ${ f.n.padEnd( 5 ) } ${ f.level } ${ f.core }  rooms ${ got.dots.map( d => d.name ).join( ', ' ) }   ${ errs.length ? 'FAIL ' + errs.join( '; ' ) : 'ok' }` );
		for ( const e of errs ) bad.push( 'flat ' + f.n + ': ' + e );
	}
	if ( cons.length ) { console.log( 'console:\n  ' + [ ...new Set( cons ) ].join( '\n  ' ) ); bad.push( 'console not clean' ); }
	console.log( bad.length ? `\nFAIL (${ bad.length })` : '\nPASS' );
	console.log( 'shots in ' + OUT );
	await b.close();
	process.exit( bad.length ? 1 : 0 );
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
