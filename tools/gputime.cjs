#!/usr/bin/env node
/* What each PASS costs on the GPU, from WebGPU timestamp queries rather than
 * from the wall clock - the wall clock swings 30% between loads and cannot
 * tell the prepass from the grade. Needs `?ts=1`, which asks the backend for
 * a query pool, and Chrome's allow_unsafe_apis for the timestamp feature.
 *
 *   node tools/gputime.cjs [page] [w] [h] [dsf] [frames] [extra query]
 *   node tools/gputime.cjs lab.html 1600 900 2 60
 *   node tools/gputime.cjs index.html 1600 900 2 60 'rail=0&hover=7'
 *
 * Every render call of a frame is listed in the order the renderer makes it,
 * labelled from the render target it draws into, with the median over the
 * sampled frames. The sum is the frame's GPU time; the page's own wall clock
 * is printed beside it so a CPU-bound page is obvious.                     */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );

const PAGE = process.argv[ 2 ] || 'lab.html';
const W = + ( process.argv[ 3 ] || 1600 ), H = + ( process.argv[ 4 ] || 900 );
const DSF = + ( process.argv[ 5 ] || 2 ), N = + ( process.argv[ 6 ] || 60 );
const EXTRA = process.argv[ 7 ] || '';

const med = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--enable-dawn-features=allow_unsafe_apis',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-gputime' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	const url = 'http://127.0.0.1:8777/' + PAGE + '?ts=1' + ( EXTRA ? '&' + EXTRA : '' );
	await p.goto( url, { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 13000 );                       // let the Scene 2 warm finish

	const has = await p.evaluate( () => {
		const R = window.__renderer;
		return !! ( R && R.backend && R.backend.timestampQueryPool
			&& R.backend.timestampQueryPool.render );
	} );
	if ( ! has ) {
		console.log( 'no timestamp query pool - the adapter did not expose timestamp-query' );
		await b.close(); process.exit( 1 );
	}

	/* nothing is measured until the page is actually drawing: a compile holds
	 * the loop off, and a frame that is not drawn reads as one vsync. */
	await p.waitForFunction( () => {
		const a = window.__perf && window.__perf.rendered || 0;
		window.__invalidate( 4 );
		return new Promise( r => requestAnimationFrame( () => requestAnimationFrame( () => {
			r( ( window.__perf.rendered || 0 ) > a );
		} ) ) );
	}, { timeout: 120000, polling: 400 } );

	const out = await p.evaluate( async ( n ) => {
		const R = window.__renderer, P = window.__parts || {};
		/* label every render call from the target it draws into: the two scene
		 * passes are known by name, everything else by its size, which is what
		 * separates a bloom mip from the output quad. */
		const label = ( rt ) => {
			if ( ! rt ) return 'output(canvas)';
			if ( P.prePass && rt === P.prePass.renderTarget ) return 'prepass';
			if ( P.scenePass && rt === P.scenePass.renderTarget ) return 'scene';
			const t = rt.texture && rt.texture.name;
			return ( t ? t : 'rt' ) + ' ' + rt.width + 'x' + rt.height;
		};
		const insp = R.inspector;
		const calls = new Map();                // uid -> { name, seq, frame }
		const _begin = insp.beginRender.bind( insp );
		let seq = 0;
		insp.beginRender = ( uid, scene, camera, rt ) => {
			const m = /^r:\d+:\S+?:f(\d+)$/.exec( uid );
			calls.set( uid, { name: label( rt ), seq: seq ++, frame: m ? + m[ 1 ] : 0 } );
			return _begin( uid, scene, camera, rt );
		};

		/* Queries are resolved in ROUNDS, never per frame: a resolve that is
		 * still in flight hands back the same promise while the pool resets
		 * its offsets underneath it, and the numbers come back scrambled.
		 * A round is small enough that the 256-query pool never wraps. */
		const ROUND = 6;
		const rows = new Map();                 // seq-in-frame + name -> ms[]
		const walls = [], frameSum = [];
		let draws = 0, tris = 0;
		for ( let r = 0; r * ROUND < n; r ++ ) {
			calls.clear();
			for ( let i = 0; i < ROUND; i ++ ) {
				const t0 = performance.now();
				window.__invalidate( 2 );
				await new Promise( k => requestAnimationFrame( k ) );
				walls.push( performance.now() - t0 );
				draws = R.info.render.drawCalls || draws;
				tris = R.info.render.triangles || tris;
			}
			await R.resolveTimestampsAsync( 'render' );
			const map = R.backend.timestampQueryPool.render.timestamps;
			/* group by frame, then by the call's place in that frame */
			const byFrame = new Map();
			for ( const [ uid, ms ] of map ) {
				const c = calls.get( uid );
				if ( ! c ) continue;
				if ( ! byFrame.has( c.frame ) ) byFrame.set( c.frame, [] );
				byFrame.get( c.frame ).push( { ...c, ms } );
			}
			for ( const list of byFrame.values() ) {
				list.sort( ( a, b ) => a.seq - b.seq );
				let sum = 0;
				list.forEach( ( c, i ) => {
					sum += c.ms;
					const key = i + '|' + c.name;
					if ( ! rows.has( key ) ) rows.set( key, [] );
					rows.get( key ).push( c.ms );
				} );
				if ( list.length ) frameSum.push( sum );
			}
		}
		return { rows: [ ...rows ].map( ( [ k, v ] ) => ( { key: k, ms: v } ) ),
			walls, frameSum, draws, tris,
			density: window.__density ? window.__density() : null };
	}, N );

	const rows = out.rows.map( r => {
		const [ order, name ] = r.key.split( '|' );
		return { order: + order, name, ms: med( r.ms ), n: r.ms.length };
	} ).sort( ( a, b ) => a.order - b.order );

	const d = out.density || {};
	console.log( `page ${ PAGE }${ EXTRA ? '?' + EXTRA : '' }   ${ W }x${ H } @${ DSF }` +
		`   pr ${ d.pr !== undefined ? d.pr : '?' }   ${ d.mpx !== undefined ? d.mpx + ' Mpx' : '' }` +
		`   ${ out.draws } draws   ${ ( out.tris / 1e6 ).toFixed( 2 ) } M tris\n` );
	console.log( 'pass                                     gpu ms   frames' );
	let sum = 0;
	for ( const r of rows ) {
		sum += r.ms;
		console.log( `  ${ String( r.order ).padStart( 2 ) } ${ r.name.padEnd( 34 ) }` +
			`${ r.ms.toFixed( 2 ).padStart( 7 ) }  ${ String( r.n ).padStart( 6 ) }` );
	}
	console.log( `  ${ ''.padEnd( 37 ) }${ '-'.repeat( 7 ) }` );
	console.log( `  ${ 'GPU total (sum of medians)'.padEnd( 37 ) }${ sum.toFixed( 2 ).padStart( 7 ) }` );
	console.log( `  ${ 'GPU per frame (median)'.padEnd( 37 ) }${ med( out.frameSum ).toFixed( 2 ).padStart( 7 ) }` );
	console.log( `  ${ 'wall clock (median rAF)'.padEnd( 37 ) }${ med( out.walls ).toFixed( 2 ).padStart( 7 ) }` );

	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
