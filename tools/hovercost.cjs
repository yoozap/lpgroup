#!/usr/bin/env node
/* What HOVERING a storey costs, and what else is standing in the frame while
 * it is open - measured in one page boot, the configurations interleaved, so
 * the machine's 30% drift between loads cannot fake a win.
 *
 *   node tools/hovercost.cjs [w] [h] [dsf] [rounds]
 *
 * ADAPT is off (`?moveres=1`), so the density is fixed and every row is
 * comparable: this rig asks what is IN the frame, not how big it is. The
 * supersampled still frame is measured separately by tools/stillcost.cjs. */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const W = + ( process.argv[ 2 ] || 1600 ), H = + ( process.argv[ 3 ] || 900 );
const DSF = + ( process.argv[ 4 ] || 2 ), ROUNDS = + ( process.argv[ 5 ] || 3 );
const med = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-hover' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/index.html?rail=0&moveres=1',
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 22000 );                  // the hero's Scene 2 warm, then quiet

	// a style switch for every blurred panel that can sit over the canvas
	await p.evaluate( () => {
		const st = document.createElement( 'style' );
		st.id = 'nobd';
		st.textContent = '*{backdrop-filter:none !important;-webkit-backdrop-filter:none !important}';
		st.disabled = true;
		document.head.appendChild( st );
	} );

	const measure = ( n = 40 ) => p.evaluate( async ( n ) => {
		const ts = [];
		for ( let i = 0; i < n + 10; i ++ ) {
			const t0 = performance.now();
			window.__invalidate( 2 );
			await new Promise( r => requestAnimationFrame( r ) );
			if ( i >= 10 ) ts.push( performance.now() - t0 );
		}
		ts.sort( ( a, b ) => a - b );
		const R = window.__renderer;
		return { med: + ts[ ts.length >> 1 ].toFixed( 2 ),
			p95: + ts[ Math.floor( ts.length * 0.95 ) ].toFixed( 2 ),
			draws: R.info.render.drawCalls, tris: R.info.render.triangles };
	}, n );

	/* What the page draws before the pointer has ever touched it - the row
	 * every other row should be compared against. */
	const cold = await measure();
	const coldFloor = await p.evaluate( () => window.__floor() );
	console.log( `cold (pointer never moved)  ${ cold.med } ms   ${ cold.draws } draws   ` +
		`${ ( cold.tris / 1e6 ).toFixed( 2 ) } M tris   flat ${ JSON.stringify( coldFloor.slots ) }\n` );

	/* find a point on the facade that lights a storey */
	let pt = null;
	for ( const fx of [ 0.62, 0.70, 0.54, 0.78, 0.46 ] ) {
		for ( const fy of [ 0.52, 0.44, 0.60, 0.36, 0.68 ] ) {
			const x = Math.round( W * fx ), y = Math.round( H * fy );
			await p.mouse.move( x, y );
			await sleep( 260 );
			const f = await p.evaluate( () => window.__floor() );
			if ( f.hot ) { pt = [ x, y, f.hot ]; break; }
		}
		if ( pt ) break;
	}
	if ( ! pt ) { console.log( 'no storey answered the pointer - is the hero in scene 1?' ); await b.close(); process.exit( 1 ); }
	console.log( `hover point ${ pt[ 0 ] },${ pt[ 1 ] } lights storey ${ pt[ 2 ] }\n` );

	const away = async () => { await p.mouse.move( Math.round( W * 0.06 ), Math.round( H * 0.9 ) );
		await sleep( 900 ); };
	const over = async () => { await p.mouse.move( pt[ 0 ], pt[ 1 ] ); await sleep( 900 ); };
	const blur = ( on ) => p.evaluate( ( on ) => {
		document.getElementById( 'nobd' ).disabled = on;
		window.__invalidate( 10 );
	}, on );
	const tag = ( on ) => p.evaluate( ( on ) => {
		const t = document.getElementById( 'floortag' );
		if ( t ) t.style.visibility = on ? '' : 'hidden';
		window.__invalidate( 10 );
	}, on );
	/* Hiding the flat is a measurement, not a state: nothing restores it here,
	 * because the page shows it itself the next time a storey is hovered.
	 * (An earlier version of this rig restored `visible` from a remembered
	 * flag and left the flat standing through every later row.) */
	const flat = ( on ) => p.evaluate( ( on ) => {
		if ( on ) return;
		for ( const g of [ window.__scene.getObjectByName( 'group_flat' ),
			window.__scene.getObjectByName( 'group_flat_b' ) ] ) {
			if ( g ) g.visible = false;
		}
		window.__invalidate( 10 );
	}, on );

	/* The sheet of glass laid in the opening. Like `flat` above this is a
	 * measurement and not a state: the page puts the panes back itself the
	 * next time a storey is placed. */
	const glass = ( on ) => p.evaluate( ( on ) => {
		if ( on ) return;
		for ( const n of [ 'floor_glass_a', 'floor_glass_b' ] ) {
			const g = window.__scene.getObjectByName( n );
			if ( g ) g.visible = false;
		}
		window.__invalidate( 10 );
	}, on );

	/* every row is a named setup; they run in this order, ROUNDS times, and
	 * the medians of the rounds are compared - never one run against another. */
	const cases = {
		'still, nothing hovered': async () => { await away(); await blur( true ); await tag( true ); await flat( true ); await glass( true ); },
		'hovered, storey open': async () => { await over(); await blur( true ); await tag( true ); await flat( true ); await glass( true ); },
		'hovered, no glass in it': async () => { await over(); await blur( true ); await tag( true ); await flat( true ); await glass( false ); },
		'hovered, no blurred panels': async () => { await over(); await blur( false ); await tag( true ); await flat( true ); await glass( true ); },
		'hovered, floortag hidden': async () => { await over(); await blur( true ); await tag( false ); await flat( true ); await glass( true ); },
		'hovered, flat not drawn': async () => { await over(); await blur( true ); await tag( true ); await flat( false ); await glass( true ); },
		'still, no blurred panels': async () => { await away(); await blur( false ); await tag( true ); await flat( true ); await glass( true ); },
	};

	const acc = {};
	for ( let r = 0; r < ROUNDS; r ++ ) {
		for ( const [ name, setup ] of Object.entries( cases ) ) {
			await setup();
			await sleep( 400 );
			const m = await measure();
			( acc[ name ] || ( acc[ name ] = [] ) ).push( m );
			process.stdout.write( '.' );
		}
	}
	console.log( '\n' );
	const d = await p.evaluate( () => window.__density() );
	console.log( `index.html?rail=0&moveres=1   ${ W }x${ H } @${ DSF }   pr ${ d.pr }   ${ d.mpx } Mpx\n` );
	console.log( 'setup                             ms    p95   draws    M tris' );
	for ( const [ name, runs ] of Object.entries( acc ) ) {
		console.log( `  ${ name.padEnd( 30 ) }${ med( runs.map( x => x.med ) ).toFixed( 1 ).padStart( 6 ) }` +
			`${ med( runs.map( x => x.p95 ) ).toFixed( 1 ).padStart( 7 ) }` +
			`${ String( med( runs.map( x => x.draws ) ) ).padStart( 8 ) }` +
			`${ ( med( runs.map( x => x.tris ) ) / 1e6 ).toFixed( 2 ).padStart( 10 ) }` );
	}
	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
