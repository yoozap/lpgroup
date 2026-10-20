#!/usr/bin/env node
/* What the page COSTS IN MEMORY, state by state - the number in Activity
 * Monitor, not the JS heap.
 *
 * The JS heap is the small half and it is the only half `perf-rig` has ever
 * reported (`mem`, ~370 MB). What a visitor sees is the renderer process
 * plus the GPU process, and on this page most of that is render TARGETS:
 * the pre-pass writes a packed normal and a velocity, the beauty pass a
 * colour and a velocity, TRAA keeps a history, the occlusion its own
 * buffer, bloom a mip chain - and every one of them is sized from the
 * current pixel ratio. Supersampling a parked frame to FLAT_MAX_MPX
 * multiplies all of them at once.
 *
 *   node tools/memcost.cjs [page] [w] [h] [dsf] [extra query]
 *   node tools/memcost.cjs index.html                 # as it ships
 *   node tools/memcost.cjs index.html 1600 900 2 'ss=1&flatss=1'   # no supersample
 *
 * Prints, per state: the pixel ratio and megapixels it settled at, the JS
 * heap, three's own texture/geometry counts, the bytes held by every render
 * target the graph owns, and the RSS of every Chrome process.           */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), { execSync } = require( 'child_process' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const PAGE = process.argv[ 2 ] || 'index.html';
const W = + ( process.argv[ 3 ] || 1600 ), H = + ( process.argv[ 4 ] || 900 );
const DSF = + ( process.argv[ 5 ] || 2 );
const EXTRA = process.argv[ 6 ] || '';

const PROFILE = path.join( os.tmpdir(), 'lp-mem' );
require( 'fs' ).rmSync( PROFILE, { recursive: true, force: true } );

/* Every Chrome process this rig started, in MB. The GPU process is the one
 * that holds the targets and it is not the one puppeteer talks to, so a
 * per-process number from inside the page can never see it. */
const rss = () => {
	try {
		const out = execSync( `ps -axo rss=,command= | grep "${ PROFILE }" | grep -v grep`, { encoding: 'utf8' } );
		let total = 0; const parts = [];
		for ( const line of out.trim().split( '\n' ) ) {
			const m = line.trim().match( /^(\d+)\s+(.*)$/ );
			if ( ! m ) continue;
			const mb = + m[ 1 ] / 1024;
			total += mb;
			const t = /--type=(\w+)/.exec( m[ 2 ] );
			parts.push( [ t ? t[ 1 ] : 'browser', mb ] );
		}
		parts.sort( ( a, b ) => b[ 1 ] - a[ 1 ] );
		return { total, top: parts.slice( 0, 4 ) };
	} catch ( e ) { return { total: 0, top: [] }; }
};

/* Every render target the node graph owns, and what it costs. three keeps
 * them on the pass nodes; the sizes are the drawing buffer's, not the
 * window's, so they move with the pixel ratio. */
const TARGETS = () => {
	const BYTES = { 1023: 4, 1022: 3, 1021: 2, 1028: 1, 1029: 2 };   // RGBA/RGB/RG/R
	const TYPE = { 1009: 1, 1010: 1, 1012: 2, 1013: 2, 1014: 4, 1015: 4, 1016: 2, 1017: 4, 1020: 4, 1011: 1 };
	const seen = new Set(); const rows = [];
	const add = ( label, rt ) => {
		if ( ! rt || seen.has( rt ) ) return;
		seen.add( rt );
		const w = rt.width || 0, h = rt.height || 0;
		const texs = rt.textures || ( rt.texture ? [ rt.texture ] : [] );
		let bytes = 0;
		for ( const t of texs ) {
			const fmt = BYTES[ t.format ] ?? 4;
			const ty = TYPE[ t.type ] ?? 1;
			bytes += w * h * fmt * ty;
		}
		if ( rt.depthTexture ) bytes += w * h * 4;
		else if ( rt.depthBuffer ) bytes += w * h * 4;
		rows.push( { label, w, h, n: texs.length, mb: bytes / 1048576 } );
	};
	const P = window.__parts || {};
	for ( const k of Object.keys( P ) ) {
		const o = P[ k ];
		if ( ! o ) continue;
		add( k, o.renderTarget || o._renderTarget );
		if ( o._rtt ) add( k + '.rtt', o._rtt );
	}
	/* ...and everything else the renderer is holding, which is where the
	 * TRAA history and the bloom mips live - they are not on `__parts`. */
	const R = window.__renderer;
	const back = R && R.backend && R.backend.get ? null : null;
	return { rows, total: rows.reduce( ( s, r ) => s + r.mb, 0 ), back };
};

const probe = ( p ) => p.evaluate( `( () => {
	const R = window.__renderer;
	const d = window.__density ? window.__density() : {};
	const m = ( performance.memory || {} );
	return {
		pr: d.pr, mpx: d.mpx, still: d.still, ss: d.ss, inFlat: d.inFlat,
		heap: Math.round( ( m.usedJSHeapSize || 0 ) / 1048576 ),
		heapCap: Math.round( ( m.jsHeapSizeLimit || 0 ) / 1048576 ),
		geo: R.info.memory.geometries, tex: R.info.memory.textures,
		draws: R.info.render.drawCalls, tris: R.info.render.triangles,
		targets: ( ${ TARGETS.toString() } )()
	};
} )()` );

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + PROFILE ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	/* A sample taken without this is "resident", which on a page that has
	 * just decoded a 12 MB model is mostly garbage that has not been
	 * collected yet - it fell 2093 -> 639 MB over half a minute of doing
	 * nothing. Collecting first turns the number into what is HELD. */
	const cdp = await p.target().createCDPSession();
	await cdp.send( 'HeapProfiler.enable' );
	const gc = async () => { try { await cdp.send( 'HeapProfiler.collectGarbage' ); } catch ( e ) {} };
	await p.goto( 'http://127.0.0.1:8777/' + PAGE + ( EXTRA ? '?' + EXTRA : '' ),
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );

	console.log( `page ${ PAGE }${ EXTRA ? '?' + EXTRA : '' }   ${ W }x${ H } @${ DSF }\n` );
	const seen = [];
	const state = async ( name, settle = 3000 ) => {
		await sleep( settle );
		await gc(); await sleep( 400 );
		const s = await probe( p );
		const r = rss();
		seen.push( { name, s, r } );
		console.log( `${ name.padEnd( 26 ) } pr ${ String( s.pr ).padStart( 5 ) }  ${
			String( s.mpx ).padStart( 6 ) } Mpx   heap ${ String( s.heap ).padStart( 4 ) } MB   ` +
			`targets ${ s.targets.total.toFixed( 0 ).padStart( 5 ) } MB   RSS ${ r.total.toFixed( 0 ).padStart( 5 ) } MB` );
		return s;
	};

	await state( 'street, just booted', 2000 );
	await state( 'street, parked 12 s', 12000 );
	// the flat, which is where the supersample budget is biggest
	await p.evaluate( () => window.LP && window.LP.setScene && window.LP.setScene( 2 ) );
	await state( 'scene 2', 9000 );
	await p.evaluate( () => window.__focus && window.__focus( 0 ) );
	await state( 'one flat open', 6000 );
	await state( 'flat, parked 20 s', 20000 );

	const worst = seen.reduce( ( a, x ) => x.r.total > a.r.total ? x : a, seen[ 0 ] );
	console.log( `\nworst state: ${ worst.name } - ${ worst.r.total.toFixed( 0 ) } MB resident` );
	console.log( 'by process: ' + worst.r.top.map( t => `${ t[ 0 ] } ${ t[ 1 ].toFixed( 0 ) } MB` ).join( ', ' ) );
	console.log( `three holds ${ worst.s.geo } geometries, ${ worst.s.tex } textures;` +
		` JS heap ${ worst.s.heap } of ${ worst.s.heapCap } MB\n` );
	console.log( 'render targets in that state:' );
	for ( const t of worst.s.targets.rows.sort( ( a, b ) => b.mb - a.mb ) )
		console.log( `  ${ t.label.padEnd( 14 ) } ${ t.w }x${ t.h }  x${ t.n }  ${ t.mb.toFixed( 1 ) } MB` );
	await b.close();
} )();
