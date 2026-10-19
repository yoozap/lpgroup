#!/usr/bin/env node
/* What the page draws at each depth of scene 2 - the street, the storey as a
 * drawing, one flat open, and standing inside a room - with the per-pass GPU
 * time from timestamp queries beside the draw counts.
 *
 *   node tools/flatcost.cjs [w] [h] [dsf] [frames]
 *
 * The question it exists to answer: how much of the CITY is still being
 * submitted once the camera is under a ceiling, and what the frame would
 * have left to spend if it were not.                                      */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const W = + ( process.argv[ 2 ] || 1600 ), H = + ( process.argv[ 3 ] || 900 );
const DSF = + ( process.argv[ 4 ] || 2 ), N = + ( process.argv[ 5 ] || 24 );
const med = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--enable-dawn-features=allow_unsafe_apis',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-flatcost' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/index.html?ts=1&rail=0',
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 20000 );

	const hasTs = await p.evaluate( () => {
		const R = window.__renderer;
		return !! ( R && R.backend && R.backend.timestampQueryPool
			&& R.backend.timestampQueryPool.render );
	} );

	const probe = () => p.evaluate( async ( n, hasTs ) => {
		const R = window.__renderer, P = window.__parts || {};
		const label = ( rt ) => {
			if ( ! rt ) return 'output(canvas)';
			if ( P.prePass && rt === P.prePass.renderTarget ) return 'prepass';
			if ( P.scenePass && rt === P.scenePass.renderTarget ) return 'scene';
			const t = rt.texture && rt.texture.name;
			return ( t ? t : 'rt' ) + ' ' + rt.width + 'x' + rt.height;
		};
		let rows = new Map(), frameSum = [];
		const insp = R.inspector;
		let restore = null, calls = new Map(), seq = 0;
		if ( hasTs && insp ) {
			const _begin = insp.beginRender.bind( insp );
			insp.beginRender = ( uid, scene, camera, rt ) => {
				const m = /^r:\d+:\S+?:f(\d+)$/.exec( uid );
				calls.set( uid, { name: label( rt ), seq: seq ++, frame: m ? + m[ 1 ] : 0 } );
				return _begin( uid, scene, camera, rt );
			};
			restore = () => { insp.beginRender = _begin; };
		}
		const walls = []; let draws = 0, tris = 0;
		const ROUND = 6;
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
			if ( ! hasTs ) continue;
			await R.resolveTimestampsAsync( 'render' );
			const map = R.backend.timestampQueryPool.render.timestamps;
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
		if ( restore ) restore();
		const m = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };
		return { walls: + m( walls ).toFixed( 2 ), gpu: + m( frameSum ).toFixed( 2 ),
			draws, tris, density: window.__density ? window.__density() : null,
			rows: [ ...rows ].map( ( [ k, v ] ) => ( { key: k, ms: + m( v ).toFixed( 2 ) } ) ) };
	}, N, hasTs );

	const states = [
		[ 'street (scene 1)', async () => { await p.evaluate( () => window.__storey( 0 ) ); await sleep( 6000 ); } ],
		[ 'floor view (storey as a drawing)', async () => { await p.evaluate( () => window.__storey( 7, 'plan' ) ); await sleep( 6500 ); } ],
		[ 'one flat open', async () => { await p.evaluate( () => window.__focus( 0 ) ); await sleep( 4500 ); } ],
		[ 'inside a room', async () => { await p.evaluate( () => window.__room( 0 ) ); await sleep( 4500 ); } ],
	];

	const out = [];
	for ( const [ name, go ] of states ) {
		await go();
		const r = await probe();
		out.push( [ name, r ] );
		process.stderr.write( `${ name }: ${ r.draws } draws  ${ r.gpu } gpu ms\n` );
	}

	console.log( `\n${ W }x${ H } @${ DSF }   ${ hasTs ? 'timestamps on' : 'NO timestamps' }\n` );
	console.log( 'state                                draws      M tris   pr      gpu ms   wall ms' );
	for ( const [ name, r ] of out ) {
		const d = r.density || {};
		console.log( `  ${ name.padEnd( 34 ) }${ String( r.draws ).padStart( 5 ) }` +
			`${ ( r.tris / 1e6 ).toFixed( 2 ).padStart( 11 ) }` +
			`${ String( d.pr ?? '?' ).padStart( 7 ) }` +
			`${ r.gpu.toFixed( 2 ).padStart( 10 ) }${ r.walls.toFixed( 2 ).padStart( 10 ) }` );
	}
	if ( hasTs ) for ( const [ name, r ] of out ) {
		console.log( `\n  ${ name } - per pass` );
		for ( const row of r.rows.sort( ( a, b ) => +a.key.split( '|' )[ 0 ] - +b.key.split( '|' )[ 0 ] ) ) {
			const [ o, nm ] = row.key.split( '|' );
			console.log( `    ${ String( o ).padStart( 2 ) } ${ nm.padEnd( 32 ) }${ row.ms.toFixed( 2 ).padStart( 7 ) }` );
		}
	}
	console.log( '' );
	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
