#!/usr/bin/env node
/* Headless perf rig for the Public Market page.
 *
 *   node tools/perf-rig.cjs [--tag name] [--url http://127.0.0.1:8777/] [--scene2] [--shot]
 *
 * Boots the page in a real headless Chrome with WebGPU on Metal, counts the
 * GPU pipelines and shader modules three builds, times the boot phases the
 * page marks in window.__perf, then samples steady state frame times.
 * Writes one JSON line per run to tools/perf-log.jsonl and prints a summary.
 */
const PUP = '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core';
const puppeteer = require( PUP );
const fs = require( 'fs' ), path = require( 'path' );

const arg = ( k, d ) => { const i = process.argv.indexOf( '--' + k ); return i > 0 ? process.argv[ i + 1 ] : d; };
const has = ( k ) => process.argv.includes( '--' + k );

const URL_ = arg( 'url', 'http://127.0.0.1:8777/lab.html' );
const TAG = arg( 'tag', 'run' );
const SHOTDIR = arg( 'shotdir', path.join( __dirname, '..', 'perf-shots' ) );
const W = + arg( 'w', 1600 ), H = + arg( 'h', 900 ), DSF = + arg( 'dsf', 2 );

const HOOK = `
window.__gpu = { pipelines: 0, pipelinesAsync: 0, shaders: 0, firstPipeline: 0, lastPipeline: 0 };
( () => {
  const mark = ( k ) => { const t = performance.now();
    if ( ! window.__gpu.firstPipeline ) window.__gpu.firstPipeline = t;
    window.__gpu.lastPipeline = t; window.__gpu[ k ] ++; };
  const P = window.GPUDevice && GPUDevice.prototype;
  if ( P ) {
    const a = P.createRenderPipeline, b = P.createRenderPipelineAsync, c = P.createShaderModule;
    P.createRenderPipeline = function ( ...x ) { mark( 'pipelines' ); return a.apply( this, x ); };
    P.createRenderPipelineAsync = function ( ...x ) { mark( 'pipelinesAsync' ); return b.apply( this, x ); };
    P.createShaderModule = function ( ...x ) { window.__gpu.shaders ++; return c.apply( this, x ); };
  }
  window.__long = [];
  try { new PerformanceObserver( ( l ) => { for ( const e of l.getEntries() )
    window.__long.push( [ Math.round( e.startTime ), Math.round( e.duration ) ] ); } )
    .observe( { entryTypes: [ 'longtask' ] } ); } catch ( e ) {}
} )();
`;

const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );

( async () => {
	const browser = await puppeteer.launch( {
		headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + path.join( require( 'os' ).tmpdir(), 'lp-perf-prof' ) ],
	} );
	const page = await browser.newPage();
	await page.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await page.evaluateOnNewDocument( HOOK );
	const logs = [];
	page.on( 'console', ( m ) => logs.push( m.text().slice( 0, 300 ) ) );
	page.on( 'pageerror', ( e ) => logs.push( 'PAGEERROR ' + e.message.slice( 0, 300 ) ) );

	const t0 = Date.now();
	await page.goto( URL_, { waitUntil: 'domcontentloaded', timeout: 120000 } );
	await page.waitForFunction(
		"document.getElementById('boot') && document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 200 } );
	const bootMs = Date.now() - t0;

	// steady state, scene 1 hero.  `force` keeps a frame owed every tick, so
	// this measures what a drawn frame costs even on a page that idles.
	await sleep( 1200 );
	const sample = async ( n = 120, force = true ) => page.evaluate( ( n, force ) => new Promise( ( res ) => {
		const ts = []; let last = performance.now();
		const tick = () => { if ( force && window.__invalidate ) window.__invalidate( 2 );
			const t = performance.now(); ts.push( t - last ); last = t;
			if ( ts.length < n ) requestAnimationFrame( tick ); else res( ts ); };
		requestAnimationFrame( tick );
	} ), n, force );
	const stat = ( a ) => { const s = [ ...a ].sort( ( x, y ) => x - y );
		return { med: + s[ s.length >> 1 ].toFixed( 2 ), p95: + s[ Math.floor( s.length * 0.95 ) ].toFixed( 2 ),
			max: + s[ s.length - 1 ].toFixed( 2 ) }; };
	const hero = stat( await sample() );

	// does the page actually stop drawing when nothing happens?
	const r0 = await page.evaluate( () => ( window.__perf && window.__perf.rendered ) || 0 );
	await sample( 90, false );
	const idleDrawn = await page.evaluate( ( r0 ) => ( ( window.__perf && window.__perf.rendered ) || 0 ) - r0, r0 );

	const out = { tag: TAG, when: new Date().toISOString(), bootMs, hero, idleDrawn };

	out.perf = await page.evaluate( () => window.__perf || null );
	out.gpu = await page.evaluate( () => window.__gpu );
	out.long = await page.evaluate( () => {
		const l = window.__long || [];
		return { count: l.length, total: l.reduce( ( s, e ) => s + e[ 1 ], 0 ), worst: Math.max( 0, ...l.map( e => e[ 1 ] ) ) };
	} );
	out.net = await page.evaluate( () => {
		const r = performance.getEntriesByType( 'resource' );
		const by = {}; let total = 0;
		for ( const e of r ) { const n = e.name.split( '/' ).pop().split( '?' )[ 0 ];
			const b = e.transferSize || e.encodedBodySize || 0; total += b;
			by[ n ] = Math.round( b / 1024 ); }
		return { totalKB: Math.round( total / 1024 ), count: r.length,
			top: Object.entries( by ).sort( ( a, b ) => b[ 1 ] - a[ 1 ] ).slice( 0, 12 ) };
	} );
	out.mem = await page.evaluate( () => performance.memory ?
		Math.round( performance.memory.usedJSHeapSize / 1048576 ) : null );

	if ( has( 'shot' ) ) {
		fs.mkdirSync( SHOTDIR, { recursive: true } );
		await page.evaluate( () => { const h = document.getElementById( 'hud' ); if ( h ) h.style.display = 'none';
			const f = document.getElementById( 'frame' ); if ( f ) f.classList.remove( 'cmp' ); } );
		await sleep( 900 );
		await page.screenshot( { path: path.join( SHOTDIR, TAG + '-s1.png' ) } );
	}

	if ( has( 'scene2' ) ) {
		const g0 = await page.evaluate( () => window.__gpu.pipelines + window.__gpu.pipelinesAsync );
		await page.evaluate( () => document.getElementById( 's_2' ).click() );
		const trans = stat( await sample( 300 ) );     // ~5 s of the flight
		await sleep( 1500 );
		const flat = stat( await sample() );
		out.scene2 = { transition: trans, flat,
			pipelinesAdded: await page.evaluate( ( g0 ) => window.__gpu.pipelines + window.__gpu.pipelinesAsync - g0, g0 ) };
		if ( has( 'shot' ) ) {
			fs.mkdirSync( SHOTDIR, { recursive: true } );
			await page.screenshot( { path: path.join( SHOTDIR, TAG + '-s2.png' ) } );
		}
	}

	out.logs = logs.filter( l => /warm|draw objects|unmapped|ERROR|error|Warning/i.test( l ) ).slice( 0, 12 );
	fs.appendFileSync( path.join( __dirname, 'perf-log.jsonl' ), JSON.stringify( out ) + '\n' );
	console.log( JSON.stringify( out, null, 1 ) );
	await browser.close();
} )().catch( ( e ) => { console.error( e ); process.exit( 1 ); } );
