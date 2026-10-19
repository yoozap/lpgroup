#!/usr/bin/env node
/* What the FLOOR VIEW's flat hover costs per frame, and what the pieces of
 * it cost separately - measured in one page boot with the configurations
 * interleaved, so the machine's drift between rounds cannot fake a win.
 *
 *   node tools/planhover.cjs [w] [h] [dsf] [rounds] [frames]
 *
 * The dial is PINNED mid-stagger for the measurement, so every row draws
 * exactly the same geometry and the only thing that differs between them is
 * the work the reveal asks for each frame. ADAPT is off (`?moveres=1`) so
 * the density is fixed too.                                               */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const W = + ( process.argv[ 2 ] || 1600 ), H = + ( process.argv[ 3 ] || 900 );
const DSF = + ( process.argv[ 4 ] || 2 ), ROUNDS = + ( process.argv[ 5 ] || 5 );
const N = + ( process.argv[ 6 ] || 30 );
const med = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-planhover' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/index.html?rail=0&moveres=1',
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 20000 );                     // the hero's Scene 2 warm, then quiet

	// the floor view, open on a storey, with one flat held mid-stagger
	await p.evaluate( () => { window.__storey( 7, 'plan' ); } );
	await sleep( 4000 );
	await p.evaluate( () => {
		window.__sun = null;
		window.__scene.traverse( ( o ) => {
			if ( o.isLight && o.shadow && o.shadow.mapSize && o.shadow.mapSize.x >= 2048 )
				window.__sun = o;
		} );
		window.__plan2d( 1, 0.55 );           // hot, pinned mid-wipe
	} );
	await sleep( 2500 );

	/* One row. `shadow` redraws the sun's map before every frame, which is
	 * what a reveal frame does through `planWrite` -> `shadowDirty`; without
	 * it the map is the one the page has been holding since it was drawn. */
	const measure = ( shadow ) => p.evaluate( async ( shadow, n ) => {
		const R = window.__renderer, S = window.__sun;
		const ts = [];
		for ( let i = 0; i < n + 8; i ++ ) {
			if ( shadow && S ) S.shadow.needsUpdate = true;
			const t0 = performance.now();
			window.__invalidate( 2 );
			await new Promise( r => requestAnimationFrame( r ) );
			if ( i >= 8 ) ts.push( performance.now() - t0 );
		}
		ts.sort( ( a, b ) => a - b );
		return { med: + ts[ ts.length >> 1 ].toFixed( 2 ),
			p95: + ts[ Math.floor( ts.length * 0.95 ) ].toFixed( 2 ),
			draws: R.info.render.drawCalls, tris: R.info.render.triangles };
	}, shadow, N );

	/* ...and the same hover run for real, unpinned, timed over the frames
	 * the dial is actually moving. This is the row a visitor feels: it
	 * carries whatever density the page hands a reveal as well as the work
	 * the reveal itself asks for. */
	const live = () => p.evaluate( async () => {
		window.__plan2d( -1 );                // nothing hot: drain, then go quiet
		await new Promise( r => setTimeout( r, 2600 ) );
		const R = window.__renderer;
		/* Draw calls per REVEAL FRAME, not the last one - the frame a dial
		 * lands on always redraws the shadow map by design, so reading only
		 * the final frame reports the one case the throttle never skips. */
		const ts = [], dr = []; let px = 0;
		await new Promise( ( done ) => {
			let last = performance.now(), n = 0;
			const step = ( t ) => {
				ts.push( t - last ); last = t; n ++;
				px = R.getPixelRatio();
				if ( R.info.render.drawCalls ) dr.push( R.info.render.drawCalls );
				if ( window.__plan2d().rev[ 1 ] < 1 && n < 300 ) requestAnimationFrame( step );
				else done();
			};
			window.__plan2d( 1 );
			requestAnimationFrame( step );
		} );
		const hi = Math.max( ...dr ), lo = Math.min( ...dr );
		const shadowFrames = dr.filter( ( d ) => d > ( lo + hi ) / 2 ).length;
		/* ...and what the page hands the SETTLED plan, once the still rule
		 * and its supersample have had time to come back. The pair is the
		 * whole point: a reveal drawn at the settled density is an
		 * animation paying a parked shot's bill. */
		await new Promise( r => setTimeout( r, 3000 ) );
		const settledPr = R.getPixelRatio();
		const a = ts.slice( 2 ).sort( ( x, y ) => x - y );
		if ( ! a.length ) return { med: 0, n: 0, ms: 0, pr: 0, settledPr, lo: 0, hi: 0, shadowFrames: 0, drawn: 0 };
		return { med: + a[ a.length >> 1 ].toFixed( 2 ), n: a.length,
			ms: + a.reduce( ( s, x ) => s + x, 0 ).toFixed( 0 ),
			pr: + px.toFixed( 2 ), settledPr: + settledPr.toFixed( 2 ),
			lo, hi, shadowFrames, drawn: dr.length };
	} );

	const liveRows = [];
	for ( let r = 0; r < ROUNDS; r ++ ) {
		const L = await live();
		liveRows.push( L );
		process.stderr.write( `live ${ r + 1 }/${ ROUNDS }  ${ L.med } ms x${ L.n } ` +
			`= ${ L.ms } ms   pr ${ L.pr } (settled ${ L.settledPr })  ` +
			`draws ${ L.lo }-${ L.hi }, shadow on ${ L.shadowFrames }/${ L.drawn }\n` );
	}
	console.log( `\nlive hover (unpinned, 0.6 s reveal)` );
	console.log( `  median frame   ${ med( liveRows.map( x => x.med ) ).toFixed( 2 ) } ms` );
	console.log( `  frames drawn   ${ med( liveRows.map( x => x.n ) ) }` );
	console.log( `  wall clock     ${ med( liveRows.map( x => x.ms ) ) } ms` );
	console.log( `  pixel ratio    ${ med( liveRows.map( x => x.pr ) ) } while revealing,` +
		` ${ med( liveRows.map( x => x.settledPr ) ) } once settled` );
	console.log( `  draw calls     ${ med( liveRows.map( x => x.lo ) ) } without the shadow pass, ` +
		`${ med( liveRows.map( x => x.hi ) ) } with it` );
	console.log( `  shadow frames  ${ med( liveRows.map( x => x.shadowFrames ) ) }` +
		` of ${ med( liveRows.map( x => x.drawn ) ) } drawn` );

	// back to a held mid-wipe for the A/B below, so both rows draw the same
	await p.evaluate( () => window.__plan2d( 1, 0.55 ) );
	await sleep( 1500 );

	const rows = { 'shadow redrawn (what a reveal frame does)': [], 'shadow held': [] };
	let shape = null;
	for ( let r = 0; r < ROUNDS; r ++ ) {
		const a = await measure( true );
		const c = await measure( false );
		rows[ 'shadow redrawn (what a reveal frame does)' ].push( a.med );
		rows[ 'shadow held' ].push( c.med );
		if ( ! shape ) shape = a;
		process.stderr.write( `round ${ r + 1 }/${ ROUNDS }  ${ a.med } / ${ c.med } ms\n` );
	}

	console.log( `\n${ W }x${ H } @${ DSF }  ${ shape.draws } draws  ` +
		`${ ( shape.tris / 1e6 ).toFixed( 2 ) } M tris   ${ ROUNDS } rounds of ${ N } frames\n` );
	const base = med( rows[ 'shadow held' ] );
	for ( const [ k, v ] of Object.entries( rows ) ) {
		const m = med( v );
		console.log( `  ${ k.padEnd( 42 ) } ${ String( m.toFixed( 2 ) ).padStart( 7 ) } ms` +
			`   ${ m === base ? '' : '+' + ( m - base ).toFixed( 2 ) + ' ms  x' + ( m / base ).toFixed( 2 ) }` );
		console.log( `  ${ ' '.repeat( 42 ) }   ${ v.map( x => x.toFixed( 1 ) ).join( '  ' ) }` );
	}
	console.log( '' );
	await b.close();
} )();
