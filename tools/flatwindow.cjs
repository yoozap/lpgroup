#!/usr/bin/env node
/* Can a visitor SEE the show flat missing while it is still downloading?
 *
 * This is the rig that should have existed before the model was split, and
 * its absence is why the split shipped broken. The flat's geometry used to
 * be in the scene from boot; splitting it made it a download, which opened
 * a window - as long as that download takes - in which `groups.flat` is
 * empty. Every other rig here waits nine or fourteen seconds before it
 * looks, by which time the flat is long since in, so all of them said the
 * page was fine. The one that could have caught it was run for TIMING and
 * its pictures were never looked at.
 *
 * So this one does the opposite: it throttles the link, drives the page the
 * two ways a visitor can reach the flat, and SHOOTS - repeatedly - through
 * the whole window, reporting what `groups.flat` held in each frame.
 *
 *   node tools/flatwindow.cjs [mbps] [outdir] [query]
 *   node tools/flatwindow.cjs 4
 *   node tools/flatwindow.cjs 4 perf-shots/win 'glbsplit=0'   # the A/B
 *
 * A PASS is: no frame in which the flat is on screen and empty. It prints
 * every sample so the frames can be looked at, because that is the whole
 * point.                                                                 */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const MBPS = + ( process.argv[ 2 ] || 4 );
const OUT = process.argv[ 3 ] || path.join( __dirname, '..', 'perf-shots', 'flatwindow' );
const Q = process.argv[ 4 ] || '';
const W = 1600, H = 900;

const PROFILE = path.join( os.tmpdir(), 'lp-flatwindow' );

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
	await cdp.send( 'Network.emulateNetworkConditions', { offline: false, latency: 40,
		downloadThroughput: MBPS * 1024 * 1024 / 8, uploadThroughput: MBPS * 1024 * 1024 / 8 } );
	await p.goto( 'http://127.0.0.1:8777/index.html' + ( Q ? '?' + Q : '' ),
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 300000, polling: 50 } );
	const ready = await p.evaluate( () => performance.now() );

	/* What is on screen, and what the flat actually holds. `shown` is the
	 * question that matters: is the page DISPLAYING the flat - scene 2, or
	 * a storey parted in the street - while it has nothing to display. */
	const probe = () => p.evaluate( () => {
		const g = window.__groups ? window.__groups() : {};
		let meshes = 0;
		if ( g.flat ) g.flat.traverse( ( o ) => { if ( o.isMesh ) meshes ++; } );
		const f = window.__floor ? window.__floor() : {};
		const sc = window.__density ? window.__density() : {};
		const parted = !! ( f.hot && f.armed );
		const inScene2 = !! ( window.LP && window.LP.scene === 2 );
		return { meshes, parted, inScene2, armed: !! f.armed, hot: f.hot | 0,
			shown: parted || inScene2, t: Math.round( performance.now() ) };
	} );

	const rows = [];
	const shoot = async ( tag ) => {
		const s = await probe();
		const name = `${ how }-${ tag }`;
		await p.screenshot( { path: path.join( OUT, name + '.png' ) } );
		rows.push( { name, ...s } );
		return s;
	};

	/* FIND the facade rather than assuming where it is. A fixed point was
	 * the first version of this rig and it missed the building entirely -
	 * every sample came back `hot: 0`, the routes tested nothing, and it
	 * printed PASS. The hero rides a rail, so the block is in a different
	 * place every second; the only reliable way in is to sweep until the
	 * page itself says a storey is lit. */
	const findFacade = async () => {
		for ( let pass = 0; pass < 3; pass ++ ) {
			for ( let fy = 0.22; fy <= 0.72; fy += 0.05 ) {
				for ( let fx = 0.40; fx <= 0.92; fx += 0.04 ) {
					await p.mouse.move( W * fx, H * fy );
					await sleep( 16 );
					const hot = await p.evaluate( () =>
						( window.__floor ? window.__floor().hot : 0 ) ||
						( window.__floorUnder ? 1 : 0 ) && 0 );
					if ( hot ) return [ W * fx, H * fy ];
				}
			}
			await sleep( 400 );
		}
		return null;
	};

	if ( how === 'hover' ) {
		let at = null;
		for ( let i = 0; i < 22; i ++ ) {
			if ( ! at ) at = await findFacade();
			if ( at ) await p.mouse.move( at[ 0 ] + ( i % 2 ), at[ 1 ] );
			await sleep( 500 );
			if ( i % 3 === 0 ) await shoot( 's' + String( i ).padStart( 2, '0' ) );
		}
	} else {
		// the other way in: a CLICK, which need not come through a hover
		const at = await findFacade();
		if ( at ) await p.mouse.click( at[ 0 ], at[ 1 ] );
		else console.log( '   (never found the facade to click)' );
		for ( let i = 0; i < 22; i ++ ) {
			await sleep( 500 );
			if ( i % 3 === 0 ) await shoot( 's' + String( i ).padStart( 2, '0' ) );
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
		/* ...and reached it by the route under test. `shown` is true for a
		 * parted storey OR for scene 2, and the click route sweeps the
		 * pointer to find the facade - which arms the hover on the way. So
		 * a click that never fired would still look "reached" on the
		 * hover's evidence, and the gate it is there to test would go
		 * unexercised while the run printed PASS. Each route is held to
		 * its own signal. */
		reached.push( { how, ok: how === 'click'
			? rows.some( r => r.inScene2 )
			: rows.some( r => r.parted ) } );
		console.log( `\n${ how.toUpperCase() } at ${ MBPS } Mbps${ Q ? '  ?' + Q : '' }   veil lifted at ${ ready } ms` );
		console.log( '   t ms   flat meshes   armed  hot  scene2   showing the flat?' );
		for ( const r of rows ) {
			const danger = r.shown && r.meshes === 0;
			if ( danger ) bad ++;
			console.log( `${ String( r.t ).padStart( 7 ) }   ${ String( r.meshes ).padStart( 11 ) }` +
				`   ${ ( r.armed ? 'yes' : 'no' ).padStart( 5 ) }  ${ String( r.hot ).padStart( 3 ) }` +
				`  ${ ( r.inScene2 ? 'yes' : 'no' ).padStart( 6 ) }   ${ r.shown ? 'YES' : 'no' }` +
				( danger ? '   <-- EMPTY FLAT ON SCREEN' : '' ) );
		}
	}
	/* A route that never reached the flat proves NOTHING, and would print
	 * PASS all the same - which is the exact shape of the mistake that let
	 * the split ship. Each route has to end up showing the flat, or the run
	 * is vacuous and says so. */
	const vacuous = reached.filter( r => ! r.ok ).map( r => r.how );
	console.log( `\nframes showing an empty flat: ${ bad }` );
	for ( const r of reached )
		console.log( `  ${ r.how } reached the flat: ${ r.ok ? 'yes' : 'NO - this route tested nothing' }` );
	const ok = bad === 0 && ! vacuous.length;
	console.log( ok ? '\nPASS' : `\nFAIL${ vacuous.length ? ' (vacuous: ' + vacuous.join( ', ' ) + ')' : '' }` );
	console.log( `frames written to ${ OUT } - LOOK AT THEM; the timings alone are what` );
	console.log( 'missed this the first time.' );
	process.exit( ok ? 0 : 1 );
} )();
