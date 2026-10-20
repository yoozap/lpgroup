#!/usr/bin/env node
/* What a frame actually COSTS, off the vsync path.
 *
 * Every other rig here reads the interval between rAF callbacks, and at
 * 60 Hz that interval is the DISPLAY: a frame that fits comes back at
 * 16.7 ms whether it cost 4 ms or 16. So the ladder "tries" a rung and
 * watches for misses, and a frame's cost has never been measurable on
 * this page - see the note in render-cost.
 *
 * This rig steps outside the loop instead. It drives `pipeline.render()`
 * in a tight batch with no rAF between the calls, advancing the node
 * frame by hand (`renderer.nodes.nodeFrame.update()`) because
 * `PassNode.updateBeforeType` is FRAME and a second render in the same
 * node frame draws nothing but the output quad, then waits for the queue
 * to go quiet and divides. That is THROUGHPUT - submit plus GPU, fully
 * pipelined - which is exactly the number "best fps" means, and it is
 * free of the display's quantisation.
 *
 *   node tools/fpsmax.cjs [page] [w] [h] [dsf] [extra query]
 *   node tools/fpsmax.cjs index.html 1600 900 2
 *   node tools/fpsmax.cjs index.html 1600 900 2 'bg=live'      # price the sky
 *
 * It prints a pixel-ratio sweep (the page's own adaptive scaling is
 * suspended for it, which is why costmap's sweep reads garbage) and, for
 * the sales page, where the density ladder settled on its own.          */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const PAGE = process.argv[ 2 ] || 'index.html';
const W = + ( process.argv[ 3 ] || 1600 ), H = + ( process.argv[ 4 ] || 900 );
const DSF = + ( process.argv[ 5 ] || 2 );
const EXTRA = process.argv[ 6 ] || '';
const RATIOS = ( process.env.PR || '2,1.5,1.25,1' ).split( ',' ).map( Number );
const N = + ( process.env.N || 40 );

/* Wiped per run: a crashed rig otherwise leaves a `SingletonLock`
 * behind and every later one dies with "the browser is already
 * running" - into the output file, where it reads as an empty
 * result rather than an error. See the same note in ridecost. */
const PROFILE = path.join( os.tmpdir(), 'lp-fpsmax' );
require( 'fs' ).rmSync( PROFILE, { recursive: true, force: true } );

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + PROFILE ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	const url = 'http://127.0.0.1:8777/' + PAGE + ( EXTRA ? '?' + EXTRA : '' );
	await p.goto( url, { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 14000 );               // let the show flat's warm finish first

	const settled = await p.evaluate( () => window.__density ? window.__density() : null );

	/* The rig owns the density while it measures: the page's own
	 * `applyScale()` runs every frame and would put the pixel ratio back
	 * between the pin and the batch. */
	await p.evaluate( () => {
		window.__fpsmax = { pin: 0 };
		const R = window.__renderer;
		window.__setPR = ( r ) => {
			R.setPixelRatio( r );
			R.setSize( innerWidth, innerHeight, false );
			R.domElement.style.width = innerWidth + 'px';
			R.domElement.style.height = innerHeight + 'px';
		};
		/* Stop the rail and the loop from touching anything mid batch. */
		R.setAnimationLoop( null );
	} );

	const batch = ( n ) => p.evaluate( async ( n ) => {
		const R = window.__renderer, P = window.__parts.pipeline;
		const dev = R.backend && R.backend.device;
		/* It is `renderer._nodes.nodeFrame`, not `renderer.nodes` - the
		 * animation loop is the only other caller of its `update()`, and
		 * without the bump every pass's `updateBefore` is skipped and the
		 * batch draws the output quad over a stale target: 0 draws, 0
		 * triangles, 0.5 ms a "frame". */
		const nf = R._nodes && R._nodes.nodeFrame;
		if ( ! nf ) throw new Error( 'no nodeFrame - cannot advance the frame by hand' );
		// three warm frames so nothing in this batch is a first draw
		for ( let i = 0; i < 3; i ++ ) { if ( nf ) nf.update(); P.render(); }
		if ( dev ) await dev.queue.onSubmittedWorkDone();
		const t0 = performance.now();
		for ( let i = 0; i < n; i ++ ) { if ( nf ) nf.update(); P.render(); }
		const submitted = performance.now() - t0;
		if ( dev ) await dev.queue.onSubmittedWorkDone();
		const total = performance.now() - t0;
		return { ms: total / n, cpu: submitted / n,
			draws: R.info.render.drawCalls, tris: R.info.render.triangles,
			calls: R.info.calls };
	}, n );

	const px = ( r ) => W * r * H * r / 1e6;
	console.log( `page ${ PAGE }${ EXTRA ? '?' + EXTRA : '' }   window ${ W }x${ H } @${ DSF }   ${ N } frames a batch` );
	if ( settled ) console.log( `the page settled itself at pr ${ settled.pr } = ${ px( settled.pr ).toFixed( 2 ) } Mpx\n` );

	console.log( ' pr      Mpx     ms    cpu ms   ms/Mpx    fps   draws    tris' );
	const rows = [];
	for ( const r of RATIOS ) {
		await p.evaluate( ( r ) => window.__setPR( r ), r );
		await sleep( 350 );
		const a = await batch( N ), c = await batch( N );   // twice, keep the faster
		const m = a.ms < c.ms ? a : c;
		const mpx = px( r );
		rows.push( { r, mpx, ...m } );
		console.log( `${ r.toFixed( 2 ).padStart( 5 ) }  ${ mpx.toFixed( 2 ).padStart( 6 ) }  ${
			m.ms.toFixed( 1 ).padStart( 6 ) }  ${ m.cpu.toFixed( 1 ).padStart( 6 ) }  ${
			( m.ms / mpx ).toFixed( 2 ).padStart( 7 ) }  ${ ( 1000 / m.ms ).toFixed( 0 ).padStart( 5 ) }  ${
			String( m.draws ).padStart( 6 ) }  ${ ( m.tris / 1e6 ).toFixed( 2 ).padStart( 6 ) }M` );
	}
	/* What of the frame is GEOMETRY rather than pixels. The sweep above
	 * gives a fixed term that does not shrink with the density, and at the
	 * rung the hero settles on that term is half the frame - so the
	 * question "how much of it is the triangles the two passes submit" is
	 * the one worth asking, and the only way to ask it from outside is to
	 * take a group away and measure without it. */
	const groupPR = + ( process.env.GROUPPR || ( settled ? settled.pr : 1 ) );
	if ( process.env.GROUPS !== '0' ) {
		await p.evaluate( ( r ) => window.__setPR( r ), groupPR );
		await sleep( 350 );
		const base = Math.min( ( await batch( N ) ).ms, ( await batch( N ) ).ms );
		console.log( `\ngroups at pr ${ groupPR } = ${ px( groupPR ).toFixed( 2 ) } Mpx   whole frame ${ base.toFixed( 1 ) } ms` );
		console.log( '  hidden            ms    saves' );
		const names = await p.evaluate( () => Object.keys( window.__groups() )
			.filter( k => window.__groups()[ k ] ) );
		for ( const k of names ) {
			const was = await p.evaluate( ( k ) => {
				const g = window.__groups()[ k ]; const w = g.visible; g.visible = false; return w; }, k );
			await sleep( 120 );
			const m = Math.min( ( await batch( N ) ).ms, ( await batch( N ) ).ms );
			await p.evaluate( ( k, w ) => { window.__groups()[ k ].visible = w; }, k, was );
			console.log( `  ${ k.padEnd( 14 ) } ${ m.toFixed( 1 ).padStart( 6 ) }  ${
				( base - m ).toFixed( 1 ).padStart( 6 ) }` );
		}
		// ...and with nothing in the scene at all: the passes' own floor
		const all = await p.evaluate( () => { const g = window.__groups(); const w = {};
			for ( const k in g ) if ( g[ k ] ) { w[ k ] = g[ k ].visible; g[ k ].visible = false; } return w; } );
		await sleep( 120 );
		const empty = Math.min( ( await batch( N ) ).ms, ( await batch( N ) ).ms );
		await p.evaluate( ( w ) => { const g = window.__groups();
			for ( const k in w ) g[ k ].visible = w[ k ]; }, all );
		console.log( `  ${ 'everything'.padEnd( 14 ) } ${ empty.toFixed( 1 ).padStart( 6 ) }  ${
			( base - empty ).toFixed( 1 ).padStart( 6 ) }   <- the passes with an empty scene` );
	}

	/* ...and where it goes, at the density the page actually runs at
	 * rather than at pr 2. The two are not the same picture: the beauty
	 * pass is pixels and shrinks with the density, the pre-pass is the
	 * triangles it submits and does not, so a stage table taken at full
	 * density says nothing about the frame a visitor is served. Switching
	 * the output node drops every stage after it from the graph. */
	const STAGES = [ 'ao', 'scene', 'traa', 'bloom', 'img', 'final' ];
	const stagePR = + ( process.env.STAGEPR || ( settled ? settled.pr : 1 ) );
	await p.evaluate( ( r ) => window.__setPR( r ), stagePR );
	await sleep( 350 );
	console.log( `\nstages at pr ${ stagePR } = ${ px( stagePR ).toFixed( 2 ) } Mpx` );
	console.log( ' stage        ms   delta   draws    tris' );
	let prev = 0;
	for ( const k of STAGES ) {
		await p.evaluate( ( k ) => window.__dbg( k ), k );
		await sleep( 250 );
		const a = await batch( N ), c = await batch( N );
		const m = a.ms < c.ms ? a : c;
		console.log( `  ${ k.padEnd( 8 ) } ${ m.ms.toFixed( 1 ).padStart( 6 ) }  ${
			( prev ? '+' + ( m.ms - prev ).toFixed( 1 ) : '' ).padStart( 6 ) }  ${
			String( m.draws ).padStart( 6 ) }  ${ ( m.tris / 1e6 ).toFixed( 2 ).padStart( 6 ) }M` );
		prev = m.ms;
	}
	await p.evaluate( () => window.__dbg( 'final' ) );

	/* Fixed cost and cost per pixel, straight off the two ends of the
	 * sweep: the frame is fill bound, so the line through them says how
	 * much of it is not pixels at all. */
	if ( rows.length > 1 ) {
		const hi = rows[ 0 ], lo = rows[ rows.length - 1 ];
		const slope = ( hi.ms - lo.ms ) / ( hi.mpx - lo.mpx );
		console.log( `\n  ${ slope.toFixed( 2 ) } ms per Mpx + ${ ( lo.ms - slope * lo.mpx ).toFixed( 1 ) } ms fixed` );
	}
	await b.close();
} )();
