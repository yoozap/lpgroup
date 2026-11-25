#!/usr/bin/env node
/* Can a visitor SEE a level missing while its interior is still downloading?
 *
 * Re-pointed at the real building (2026-11-24). The interiors are downloads
 * now - web/interior/<LEVEL>.glb and cores.glb - fetched when a storey is
 * hovered or clicked, so the window the old show flat's split opened is
 * there for every level: the page can be IN the floor view of a level whose
 * geometry has not arrived. The scene's answer is the gate (`lvWith` in
 * app.js): a level is only ever opened once its part is `in` - fetched,
 * welded AND compiled.
 *
 * This throttles the link, drives the two ways in early - a hover, which
 * must only light a band and never show a level, and a click, which must
 * wait - and SHOOTS through the whole window, reporting per frame what the
 * open level actually holds on screen.
 *
 *   node tools/flatwindow.cjs [mbps] [outdir] [query]
 *   node tools/flatwindow.cjs 4
 *   node tools/flatwindow.cjs 4 perf-shots/win 'lvgate=0'   # must FAIL
 *
 * A PASS is: no frame in which scene 2 is up with its level's interior not
 * on screen, AND each route reached what it was testing (a lit band for the
 * hover, scene 2 for the click) - a route that tested nothing fails. */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const MBPS = + ( process.argv[ 2 ] || 4 );
const OUT = process.argv[ 3 ] || path.join( __dirname, '..', 'perf-shots', 'flatwindow' );
const Q = process.argv[ 4 ] || '';
const W = 1600, H = 900;
const PROFILE = path.join( os.tmpdir(), 'lp-flatwindow' );
const LEVEL = 'L07';                       // a storey with the street face in view

async function run( how ) {
	fs.rmSync( PROFILE, { recursive: true, force: true } );
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + PROFILE ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: 1 } );
	const cdp = await p.target().createCDPSession();
	await cdp.send( 'Network.enable' );
	// no cache: every interior byte comes over the throttled link
	await cdp.send( 'Network.setCacheDisabled', { cacheDisabled: true } );
	await cdp.send( 'Network.emulateNetworkConditions', { offline: false, latency: 40,
		downloadThroughput: MBPS * 1024 * 1024 / 8, uploadThroughput: MBPS * 1024 * 1024 / 8 } );
	await p.goto( 'http://127.0.0.1:8777/index.html' + ( Q ? '?' + Q : '' ),
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 300000, polling: 50 } );
	const ready = await p.evaluate( () => performance.now() );

	/* `empty` is the question: is the floor view up while the level it is
	 * open on has nothing on screen - its part not in, or none of its
	 * meshes visible. */
	const probe = () => p.evaluate( () => {
		const s = window.__lv ? window.__lv() : {};
		const part = ( s.parts || [] ).find( x => x.name === s.open );
		const inScene2 = !! ( window.LP && window.LP.scene === 2 && s.open );
		const empty = inScene2 && ! ( part && part.state === 'in' && part.shown && s.shownMeshes > 0 );
		return { open: s.open || '', state: part ? part.state : '-', meshes: s.shownMeshes | 0,
			band: s.hotLevel || '', inScene2, empty, waiting: s.waiting || '',
			t: Math.round( performance.now() ) };
	} );
	const rows = [];
	const shoot = async ( tag ) => {
		const s = await probe();
		const name = `${ how }-${ tag }`;
		await p.screenshot( { path: path.join( OUT, name + '.png' ) } );
		rows.push( { name, ...s } );
		return s;
	};
	/* WHERE the storey is: asked of the scene, not assumed - the hero rides
	 * a rail, so the block is somewhere else every second. */
	const bandXY = () => p.evaluate( ( id ) => window.__lvBandAt && ( window.__lvBandAt( id, 1, 0.45 )
		|| window.__lvBandAt( id, 2, 0.5 ) || window.__lvBandAt( id, 3, 0.5 ) ), LEVEL );

	if ( how === 'hover' ) {
		for ( let i = 0; i < 18; i ++ ) {
			const xy = await bandXY();
			if ( xy ) await p.mouse.move( xy[ 0 ] + ( i % 2 ), xy[ 1 ] );
			await sleep( 400 );
			if ( i % 3 === 0 ) await shoot( 's' + String( i ).padStart( 2, '0' ) );
		}
	} else {
		// the other way in: a CLICK, straight away, which need not come through a hover
		let xy = null;
		for ( let k = 0; k < 40 && ! xy; k ++ ) { xy = await bandXY(); if ( ! xy ) await sleep( 250 ); }
		if ( xy ) await p.mouse.click( xy[ 0 ], xy[ 1 ] );
		else console.log( '   (never found the facade to click)' );
		for ( let i = 0; i < 40; i ++ ) {
			await sleep( 300 );
			if ( i % 2 === 0 ) await shoot( 's' + String( i ).padStart( 2, '0' ) );
		}
	}
	await b.close();
	return { ready: Math.round( ready ), rows };
}

( async () => {
	fs.mkdirSync( OUT, { recursive: true } );
	let bad = 0;
	const reached = [];
	for ( const how of [ 'hover', 'click' ] ) {
		const { ready, rows } = await run( how );
		reached.push( { how, ok: how === 'click' ? rows.some( r => r.inScene2 ) : rows.some( r => r.band ) } );
		console.log( `\n${ how.toUpperCase() } at ${ MBPS } Mbps${ Q ? '  ?' + Q : '' }   veil lifted at ${ ready } ms` );
		console.log( '   t ms   band   waiting  scene2  open  part     meshes   empty level on screen?' );
		for ( const r of rows ) {
			if ( r.empty ) bad ++;
			console.log( `${ String( r.t ).padStart( 7 ) }   ${ ( r.band || '-' ).padStart( 4 ) }   ${ ( r.waiting || '-' ).padStart( 7 ) }` +
				`  ${ ( r.inScene2 ? 'yes' : 'no' ).padStart( 6 ) }  ${ ( r.open || '-' ).padStart( 4 ) }  ${ r.state.padEnd( 8 ) }` +
				` ${ String( r.meshes ).padStart( 6 ) }   ${ r.empty ? 'YES   <-- EMPTY LEVEL ON SCREEN' : 'no' }` );
		}
	}
	const vacuous = reached.filter( r => ! r.ok ).map( r => r.how );
	console.log( `\nframes showing an empty level: ${ bad }` );
	for ( const r of reached )
		console.log( `  ${ r.how } reached ${ r.how === 'click' ? 'the floor view' : 'a lit storey' }: ${ r.ok ? 'yes' : 'NO - this route tested nothing' }` );
	const ok = bad === 0 && ! vacuous.length;
	console.log( ok ? '\nPASS' : `\nFAIL${ vacuous.length ? ' (vacuous: ' + vacuous.join( ', ' ) + ')' : '' }` );
	console.log( `frames written to ${ OUT } - LOOK AT THEM.` );
	process.exit( ok ? 0 : 1 );
} )();
