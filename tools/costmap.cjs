#!/usr/bin/env node
/* Where a frame goes, measured in one page so the machine's drift cannot
 * fake a win: boot once, then switch the output node (which drops every
 * stage after it from the graph) and sweep the pixel ratio.
 *   node tools/costmap.cjs [page] [w] [h] [dsf]                           */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const PAGE = process.argv[ 2 ] || 'lab.html';
const W = + ( process.argv[ 3 ] || 1600 ), H = + ( process.argv[ 4 ] || 900 ), DSF = + ( process.argv[ 5 ] || 2 );

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + path.join( os.tmpdir(), 'lp-cost' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/' + PAGE, { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 13000 );               // let the Scene 2 warm finish first

	await p.evaluate( () => { if ( window.LP ) window.LP.setMode && window.LP.setMode( 'hero' ); } );

	const measure = async ( n = 90 ) => p.evaluate( async ( n ) => {
		const ts = [];
		for ( let i = 0; i < n + 20; i ++ ) {
			const t0 = performance.now();
			window.__invalidate( 2 );
			await new Promise( r => requestAnimationFrame( r ) );
			if ( i >= 20 ) ts.push( performance.now() - t0 );
		}
		ts.sort( ( a, b ) => a - b );
		return { med: + ts[ ts.length >> 1 ].toFixed( 2 ), p95: + ts[ Math.floor( ts.length * .95 ) ].toFixed( 2 ) };
	}, n );

	const setPR = ( r ) => p.evaluate( ( r ) => {
		const R = window.__renderer;
		R.setPixelRatio( r ); R.setSize( innerWidth, innerHeight, false );
		R.domElement.style.width = innerWidth + 'px'; R.domElement.style.height = innerHeight + 'px';
		window.__invalidate( 30 );
	}, r );
	const setStage = ( k ) => p.evaluate( ( k ) => window.__dbg( k ), k );
	const setAO = ( s ) => p.evaluate( ( s ) => { window.__parts.aoPass.resolutionScale = s;
		window.__invalidate( 30 ); }, s );

	const pr0 = await p.evaluate( () => window.__renderer.getPixelRatio() );
	const px = ( r ) => Math.round( W * r * H * r / 1e6 * 100 ) / 100;
	console.log( `page ${ PAGE }   window ${ W }x${ H }   pixelRatio ${ pr0 }   = ${ px( pr0 ) } Mpx\n` );

	console.log( 'stage               ms     delta' );
	let prev = 0;
	for ( const k of [ 'ao', 'scene', 'traa', 'bloom', 'img', 'final' ] ) {
		await setStage( k ); await sleep( 2200 );
		const m = await measure();
		console.log( `  ${ k.padEnd( 16 ) } ${ String( m.med ).padStart( 6 ) }  ${ prev ? '+' + ( m.med - prev ).toFixed( 1 ) : '' }` );
		prev = m.med;
	}

	await setStage( 'final' ); await sleep( 1500 );
	console.log( '\nAO resolution       ms' );
	for ( const s of [ 1, 0.5, 0.25 ] ) {
		await setAO( s ); await sleep( 1800 );
		const m = await measure();
		console.log( `  x${ String( s ).padEnd( 15 ) } ${ String( m.med ).padStart( 6 ) }` );
	}
	await setAO( 1 );

	console.log( '\npixelRatio          ms      Mpx   fps' );
	for ( const r of [ pr0, 1.75, 1.5, 1.25, 1.0 ] ) {
		await setPR( r ); await sleep( 1800 );
		const m = await measure();
		console.log( `  ${ String( r ).padEnd( 16 ) } ${ String( m.med ).padStart( 6 ) }  ${ String( px( r ) ).padStart( 7 ) }  ${ ( 1000 / m.med ).toFixed( 0 ).padStart( 4 ) }` );
	}
	await b.close();
} )().catch( e => { console.error( e.message ); process.exit( 1 ); } );
