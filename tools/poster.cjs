/* The hero's own first frame, captured with the document hidden, to be shown
 * while the real one is still being compiled: the boot veil's background.
 *
 *   node tools/poster.cjs [out.webp] [w] [h]      (default web/hero-poster.webp)
 *
 * Re-run it whenever the model, the look or the hero's opening pose change -
 * the veil cross-fades into the live frame, so a stale poster shows as a
 * jump. */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path=require('path'), os=require('os'), { execFileSync } = require('child_process');
const sleep = ms => new Promise( r => setTimeout( r, ms ) );
const W = + ( process.argv[ 3 ] || 1920 ), H = + ( process.argv[ 4 ] || 1080 );
( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + path.join(os.tmpdir(),'lp-poster') ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: 1 } );
	await p.goto( 'http://127.0.0.1:8777/index.html', { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')", { timeout: 240000, polling: 100 } );
	/* The frame the visitor actually gets: the one the veil lifts on. The
	 * hero is on its rail from that instant, so there is no later moment to
	 * take this from - waiting for the parked shot to settle gives a sharper
	 * picture of a pose the page never opens on. The document is hidden the
	 * moment the veil goes, and the shot taken in the next few frames. */
	await p.evaluate( () => {
		for ( const el of document.body.children )
			if ( el.id !== 'stage' ) el.style.visibility = 'hidden';
		document.documentElement.style.background = '#0d1b30';
	} );
	await sleep( 120 );
	const out = process.argv[ 2 ] || 'web/hero-poster.webp';
	const png = out.endsWith( '.webp' ) ? out.replace( /\.webp$/, '.png' ) : out;
	await p.screenshot( { path: png } );
	if ( out.endsWith( '.webp' ) ) {
		execFileSync( 'python3', [ '-c',
			'import sys;from PIL import Image;Image.open(sys.argv[1]).convert("RGB")'
			+ '.save(sys.argv[2],"WEBP",quality=72,method=6)', png, out ] );
		require( 'fs' ).unlinkSync( png );
	}
	console.log( 'captured', out, W + 'x' + H,
		Math.round( require( 'fs' ).statSync( out ).size / 1024 ) + ' KB' );
	await b.close();
} )();
