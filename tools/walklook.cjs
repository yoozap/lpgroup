#!/usr/bin/env node
/* The SAME eight places inside the building, photographed on foot, so a
 * change to how the walk is lit can be judged before | after on identical
 * frames - and a number for each: the mean luminance of the frame (Rec.709
 * on the sRGB screenshot, 0..255) with the page's HUD column left out.
 *
 *   node tools/walklook.cjs [--base=http://127.0.0.1:8777] [--out=dir]
 *        [--poses=file.json] [--q=extra&query]
 *
 * The poses are found ONCE (rooms of flat 41 on L03 and 177 on L10 at their
 * widest spot, both corridors, the C1 hall) and written to --poses if that
 * file does not exist, then read back on every later run, so two builds -
 * even two builds whose stance logic differs - are photographed from the
 * same eye. A pose is stood in with `LP.walk( {level, at, heading} )`.
 * Exit 1 if a station could not be stood in or the console is not clean.
 */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const arg = ( k, d ) => { const a = process.argv.find( s => s.startsWith( '--' + k + '=' ) ); return a ? a.slice( k.length + 3 ) : d; };
const BASE = arg( 'base', 'http://127.0.0.1:8777' );
const OUT = arg( 'out', path.join( __dirname, '..', 'perf-shots', 'walklook' ) );
const POSES = arg( 'poses', path.join( __dirname, '..', 'perf-shots', 'walklook-poses.json' ) );
const Q = arg( 'q', '' );
const W = 1600, H = 900;

( async () => {
	fs.mkdirSync( OUT, { recursive: true } );
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + path.join( os.tmpdir(), 'lp-walklook-' + process.pid ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: 1 } );
	const cons = [];
	p.on( 'console', m => { const t = m.text();
		if ( ( m.type() === 'error' || /unmapped|invalid|failed/i.test( t ) ) && ! /404|facade-|photos\//.test( t ) ) cons.push( t.slice( 0, 200 ) ); } );
	p.on( 'pageerror', e => cons.push( 'PAGEERROR ' + String( e ).slice( 0, 200 ) ) );
	await p.goto( BASE + '/index.html?lang=en' + ( Q ? '&' + Q : '' ), { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')", { timeout: 300000, polling: 100 } );
	await sleep( 2000 );
	const ev = ( f, ...a ) => p.evaluate( f, ...a );
	const until = async ( pred, ms = 60000 ) => { const t0 = Date.now(); while ( Date.now() - t0 < ms ) { if ( await p.evaluate( pred ) ) return true; await sleep( 150 ); } return false; };

	let poses = fs.existsSync( POSES ) ? JSON.parse( fs.readFileSync( POSES, 'utf8' ) ) : null;
	if ( ! poses ) {
		// any walk makes the engine; then read the places off it
		await ev( () => window.LP.walk( { flat: '41', room: 0 } ) );
		await until( '!!(window.__bw.on && window.__bw.W && !window.__lv().tweens)', 90000 );
		poses = await ev( () => {
			const Wk = window.__bw.W, D = Wk.debug, out = [];
			const unit = ( n ) => { for ( const l of Wk.levels() ) { const u = Wk.nav( l.id ).units.find( x => ! x.office && String( x.n ) === n ); if ( u ) return { level: l.id, u }; } };
			const room = ( n, pick, tag ) => { const U = unit( n ); const i = U.u.rooms.findIndex( pick ); if ( i < 0 ) return;
				const s = D.roomSpot( U.level, U.u.rooms[ i ] ); if ( s ) out.push( { tag, level: U.level, at: [ s[ 0 ], s[ 1 ] ], heading: s[ 2 ] } ); };
			const door = ( n, tag ) => { const U = unit( n ), d = U.u.doors.find( x => x.kind === 'entrance' ) || U.u.doors[ 0 ], sh = d.shut * Math.PI / 180;
				const cx = d.hinge[ 0 ] + Math.cos( sh ) * d.w / 2, cy = d.hinge[ 1 ] + Math.sin( sh ) * d.w / 2;
				let nx = - Math.sin( sh ), ny = Math.cos( sh ); if ( ! D.inPoly( U.u.P, cx + nx * 0.6, cy + ny * 0.6 ) ) { nx = - nx; ny = - ny; }
				// outside the door, looking down the corridor's longest free line
				const at = [ cx - nx * 0.9, cy - ny * 0.9 ], F = Wk.field( U.level );
				let bh = 0, bl = - 1;
				for ( let k = 0; k < 48; k ++ ) { const a = k / 48 * 2 * Math.PI; let l = 0;
					while ( l < 30 && D.fieldAt( F, at[ 0 ] + Math.cos( a ) * l, at[ 1 ] + Math.sin( a ) * l ) > 0.05 ) l += 0.1;
					if ( l > bl ) { bl = l; bh = a; } }
				out.push( { tag, level: U.level, at, heading: bh } ); };
			room( '41', ( r ) => /living/.test( r.kind || '' ), '41_living' );
			room( '41', ( r ) => /bed/.test( r.kind || '' ), '41_bedroom' );
			room( '41', ( r ) => /bath|wc|toilet/.test( r.kind || '' ), '41_bath' );
			room( '41', ( r ) => /hall|corr|entr/.test( r.kind || '' ), '41_hall' );
			door( '41', 'L03_corridor' );
			room( '177', ( r ) => /living/.test( r.kind || '' ), '177_living' );
			room( '177', ( r ) => /bed/.test( r.kind || '' ), '177_bedroom' );
			door( '177', 'L10_corridor' );
			return out;
		} );
		fs.writeFileSync( POSES, JSON.stringify( poses, null, 1 ) );
		await ev( () => window.LP.walkExit( 'street' ) );
		await until( '!window.__lv().tweens', 20000 );
	}
	const bad = [], rows = [];
	for ( const [ k, P ] of poses.entries() ) {
		const ok = await ev( ( P ) => window.LP.walk( { level: P.level, at: P.at, heading: P.heading } ), P );
		const on = ok && await until( `!!(window.__bw.on && !window.__lv().tweens && window.__bw.s && window.__bw.s.level === '${ P.level }')`, 90000 );
		if ( ! on ) { bad.push( P.tag + ': not stood in' ); continue; }
		// a little down, as a visitor looks into a room
		await ev( () => { window.__bw.step( 1, { look: { yaw: 0, pitch: - 0.12 - window.__bw.W.debug.B.p } } ); } );
		await until( '!window.__lv().compiling', 30000 );
		const r0 = await ev( () => { window.LP.invalidate( 8 ); return window.__perf.rendered; } );
		await until( `window.__perf.rendered >= ${ r0 + 6 }`, 10000 );
		await sleep( 1200 );
		const file = path.join( OUT, String( k + 1 ).padStart( 2, '0' ) + '_' + P.tag + '.png' );
		const buf = await p.screenshot( { path: file } );
		// luminance, right of the HUD column
		const lum = await ev( async ( b64 ) => {
			const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
			const c = document.createElement( 'canvas' ); c.width = img.width; c.height = img.height;
			const g = c.getContext( '2d' ); g.drawImage( img, 0, 0 );
			const x0 = Math.round( img.width * 0.22 ), y0 = Math.round( img.height * 0.1 );
			const d = g.getImageData( x0, y0, img.width - x0, img.height - y0 ).data;
			let s = 0, rb = 0, n = 0;
			for ( let i = 0; i < d.length; i += 16 ) { s += 0.2126 * d[ i ] + 0.7152 * d[ i + 1 ] + 0.0722 * d[ i + 2 ]; rb += d[ i ] - d[ i + 2 ]; n ++; }
			return { mean: s / n, warm: rb / n };
		}, Buffer.from( buf ).toString( 'base64' ) );
		rows.push( { tag: P.tag, ...lum } );
		console.log( `  ${ P.tag.padEnd( 16 ) } luminance ${ lum.mean.toFixed( 1 ) }  R-B ${ lum.warm.toFixed( 1 ) }  ${ path.basename( file ) }` );
		await ev( () => window.LP.walkExit( 'none' ) );
		await sleep( 300 );
	}
	fs.writeFileSync( path.join( OUT, 'walklook.json' ), JSON.stringify( rows, null, 1 ) );
	if ( cons.length ) { bad.push( 'console: ' + [ ...new Set( cons ) ].join( ' | ' ) ); }
	console.log( bad.length ? 'FAIL\n  ' + bad.join( '\n  ' ) : 'PASS (' + rows.length + ' stations) - LOOK AT ' + OUT );
	await b.close();
	process.exit( bad.length ? 1 : 0 );
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
