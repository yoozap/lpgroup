/* ===================================================================== *
 *  Georgian, and the machinery that puts it on the page.
 *
 *  THE KEY IS THE ENGLISH. index.html carries the prose, and it stays
 *  the source of truth: this file maps the markup as authored there,
 *  with its whitespace collapsed, to the same markup in Georgian. No
 *  `data-t` attributes anywhere, nothing to keep in step by hand, and a
 *  key that stops matching - because somebody edited the English - falls
 *  back to the English, which is the safe way for a translation to fail.
 *
 *  WHOLE ELEMENTS, NOT TEXT NODES. Half the sentences on this page have
 *  a fact in the middle of them: "<project> is a finished residential
 *  building by LP Group in <district>". Translated a fragment at a time
 *  that comes out as Georgian words in English order, because Georgian
 *  does not put the pieces where English does. So the unit is the whole
 *  element - its markup, its `data-v` spans and all - and the Georgian
 *  side is free to move them. `fill()` runs afterwards and drops the
 *  facts into wherever the Georgian put them.
 *
 *  MTAVRULI IS A FONT HERE, NOT A CASE. BPG Nino Mtavruli draws capital
 *  Georgian at the ordinary lower-case code points, so the capitals on
 *  titles are the font and not the text: every string in this file stays
 *  readable, searchable, copyable Mkhedruli. What `applyTitleFont` does
 *  is mark the elements that should be in that face - exactly the ones
 *  whose computed style says `uppercase`, because the design has already
 *  decided there what a title is, and Mtavruli is what Georgian uses
 *  where Latin uses capitals. Fifty-five rules set it; a hand-written
 *  list of them goes stale, the computed style cannot.
 *
 *  Changing the text instead - `toUpperCase()` does map Mkhedruli to the
 *  Mtavruli block - would push every title off this font and back onto
 *  Noto, which is the one thing it must not do.
 * ===================================================================== */

export const LANGS = [ 'ka', 'en' ];
export const DEFAULT_LANG = 'ka';


/* ------------------------------------------------------------ the words
 * Left: index.html's own markup, whitespace collapsed. Right: the same
 * in Georgian. Anything not here stays English. */
export const KA = {

	/* ---------------------------------------------------------- header */
	'LP': 'LP',
	'LP Group<small data-v="projectLine">Todria 11 · Rustavi</small>':
		'ელპი ჯგუფი<small data-v="projectLine"></small>',
	'About': 'შესახებ',
	'Location': 'მდებარეობა',
	'Flats': 'ბინები',
	'Prices': 'ფასები',
	'Gallery': 'გალერეა',
	'Contacts': 'კონტაქტი',
	'Book a viewing': 'დაჯავშნეთ ვიზიტი',

	/* ------------------------------------------------------------ hero */
	'LP Group ·': 'ელპი ჯგუფი ·',
	'Ready to move in': 'შესახლებისთვის მზადაა',
	'The building is ready.<br><em>Your flat is waiting.</em>':
		'შენობა მზადაა.<br><em>თქვენი ბინა გელოდებათ.</em>',
	'No waiting and no construction risk. Choose a flat online, walk through it in 3D, and get the keys right after purchase.':
		'არც ლოდინი და არც სამშენებლო რისკი. აირჩიეთ ბინა ონლაინ, დაათვალიერეთ 3D-ში და მიიღეთ გასაღები შეძენისთანავე.',
	'← Back to the street': '← უკან, ქუჩაზე',
	'← The whole floor': '← უკან, სართულზე',
	'The show flat · top floor, corner': 'საჩვენებელი ბინა · ბოლო სართული, კუთხის',
	'Floor<b data-v="tourFloor">12</b>': 'სართული<b data-v="tourFloor"></b>',
	'Area<b data-v="tourArea">77.7 m²</b>': 'ფართი<b data-v="tourArea"></b>',
	'Price<b data-v="tourPrice">$72,200</b>': 'ფასი<b data-v="tourPrice"></b>',
	'Choose flat': 'აირჩიეთ ბინა',
	'Drag to look · <b>W A S D</b> to walk · doors open as you come to them':
		'გადაათრიეთ მიმოსახედად · <b>W A S D</b> სიარულისთვის · კარები თავად იღება',
	'Living room': 'მისაღები',
	'Back to the flat': 'უკან, ბინაში',

	/* ---------------------------------------------------------- filter */
	'Rooms': 'ოთახი',
	'Any': 'ყველა',
	'Studio': 'სტუდია',
	'Floor from': 'სართული, დან',
	'Price up to': 'ფასი, მდე',
	'any': 'ყველა',
	'See them': 'ნახეთ ბინები',

	/* ----------------------------------------------------- the numbers */
	'Floors': 'სართული',
	'Flats, <span class="hi"><span data-v="available">17</span> still available</span>':
		'ბინა, <span class="hi">მათგან <span data-v="available"></span> თავისუფალი</span>',
	'Built': 'აშენებულია',
	'Right after<br>purchase': 'შეძენისთანავე',
	'Keys': 'გასაღები',
	'min': 'წთ',
	'To <span data-v="landmark">Tbilisi</span>': '<span data-v="landmark"></span>-მდე',

	/* --------------------------------------------------------- about */
	'About the project': 'პროექტის შესახებ',
	'A home you can see, touch and move into': 'სახლი, რომელსაც ხედავთ, ეხებით და სახლდებით',
	'<span data-v="project">Todria 11</span> is a finished residential building by LP Group in <span data-v="district">Todria</span>. The facade, lobby, lifts, courtyard and parking are complete. You buy exactly what you see — not a render.':
		'<span data-v="project"></span> — ელპი ჯგუფის დასრულებული საცხოვრებელი კორპუსი <span data-v="district"></span>ში. ფასადი, ჰოლი, ლიფტები, ეზო და პარკინგი მზადაა. ყიდულობთ ზუსტად იმას, რასაც ხედავთ — და არა რენდერს.',
	'See available flats': 'იხილეთ თავისუფალი ბინები',
	'Finished, not promised': 'დასრულებული, და არა დაპირებული',
	'The building is complete. Visit any day and inspect your flat in person.':
		'შენობა დასრულებულია. მობრძანდით ნებისმიერ დღეს და ადგილზე დაათვალიერეთ თქვენი ბინა.',
	'Built to last': 'აშენებული ხანგრძლივად',
	'<span data-v="frame">Monolithic reinforced-concrete frame</span>, <span data-v="insulation">100&nbsp;mm mineral-wool facade insulation</span>, <span data-v="windows">REHAU double-glazed windows</span>. Quality you can check with your own eyes.':
		'<span data-v="frame"></span>, <span data-v="insulation"></span>, <span data-v="windows"></span>. ხარისხი, რომელსაც საკუთარი თვალით შეამოწმებთ.',
	'Smart layouts': 'გააზრებული გეგმარება',
	'Bright rooms, no wasted corridors, <span data-v="balconyLine">a balcony in every flat</span>.':
		'ნათელი ოთახები, უსარგებლო დერეფნების გარეშე, <span data-v="balconyLine"></span>.',
	'Everything you need, a short walk away': 'ყველაფერი საჭირო — ფეხით სავალ მანძილზე',
	'<span data-v="district">Todria</span> gives you quiet streets for family life and quick routes to the rest of <span data-v="city">Rustavi</span>.':
		'<span data-v="district"></span> გთავაზობთ წყნარ ქუჩებს ოჯახური ცხოვრებისთვის და სწრაფ მისასვლელს <span data-v="city"></span>ის დანარჩენ ნაწილამდე.',
	'Book a site visit': 'დაჯავშნეთ ადგილზე ვიზიტი',
	'Open in Maps': 'გახსენით რუკაზე',

	/* --------------------------------------------------- availability */
	'Availability': 'თავისუფალი ბინები',
	'Choose your flat — live availability': 'აირჩიეთ ბინა — სტატუსი რეალურ დროში',
	'Click a floor on the building, then a flat on the plan. Green is available, amber is reserved, grey is sold.':
		'დააჭირეთ სართულს შენობაზე, შემდეგ კი ბინას გეგმაზე. მწვანე — თავისუფალია, ყვითელი — დაჯავშნილი, ნაცრისფერი — გაყიდული.',
	'<i class="dot-available"></i>Available': '<i class="dot-available"></i>თავისუფალი',
	'<i class="dot-reserved"></i>Reserved': '<i class="dot-reserved"></i>დაჯავშნილი',
	'<i class="dot-sold"></i>Sold': '<i class="dot-sold"></i>გაყიდული',
	'Change filters': 'შეცვალეთ ფილტრი',
	'Prices update live · confirm with a manager before purchase':
		'ფასები ახლდება რეალურ დროში · შეძენამდე დაადასტურეთ მენეჯერთან',
	'No flats match these filters. Change the floor or price range — or let a manager find one for you. <br><a class="btn btn--amber" href="#contacts">Ask a manager</a>':
		'ამ ფილტრებს ბინა არ შეესაბამება. შეცვალეთ სართული ან ფასის დიაპაზონი — ან მოძებნინეთ მენეჯერს. <br><a class="btn btn--amber" href="#contacts">ჰკითხეთ მენეჯერს</a>',
	'Ask a manager': 'ჰკითხეთ მენეჯერს',
	'Walk the show flat<b><svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 4.4v15.2L19 12z"></path></svg></b>':
		'დაათვალიერეთ საჩვენებელი ბინა<b><svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 4.4v15.2L19 12z"></path></svg></b>',
	'Can\'t decide?': 'ვერ წყვეტთ?',
	'Tell a manager what you are after — floor, rooms, budget — and they will come back with the two or three that fit.':
		'უთხარით მენეჯერს, რას ეძებთ — სართული, ოთახები, ბიუჯეტი — და ის შემოგთავაზებთ ორ-სამ შესაფერის ვარიანტს.',

	/* ------------------------------------------------------- amenities */
	'Amenities': 'ინფრასტრუქტურა',
	'Everything around your flat is finished too': 'თქვენი ბინის გარშემო ყველაფერი დასრულებულია',
	'Underground parking': 'მიწისქვეშა პარკინგი',
	'Your car stays dry, safe and close to the lift.':
		'თქვენი ავტომობილი მშრალად, უსაფრთხოდ და ლიფტთან ახლოს დგას.',
	'Secure entrance &amp; CCTV': 'დაცული შესასვლელი და ვიდეოკონტროლი',
	'Only residents and their guests get in.': 'შემოსვლა მხოლოდ მაცხოვრებლებსა და მათ სტუმრებს შეუძლიათ.',
	'Courtyard &amp; playground': 'ეზო და საბავშვო მოედანი',
	'Children play in sight of your windows.': 'ბავშვები თქვენი ფანჯრიდან დანახვად მანძილზე თამაშობენ.',
	'Modern lifts': 'თანამედროვე ლიფტები',
	'<span data-v="lifts">Şahin</span>, quiet and fast.': '<span data-v="lifts"></span> — ჩუმი და სწრაფი.',
	'Storage rooms': 'სათავსოები',
	'Space for bikes, tyres and seasonal things.': 'ადგილი ველოსიპედების, საბურავებისა და სეზონური ნივთებისთვის.',
	'Shops downstairs': 'მაღაზიები პირველ სართულზე',
	'<span data-v="shopsLine">Pharmacy and a grocery</span> on the ground floor.':
		'<span data-v="shopsLine"></span> პირველ სართულზე.',
	'Flats are delivered in <b data-v="condition">white frame</b> condition.':
		'ბინები გადაეცემა <b data-v="condition"></b> მდგომარეობაში.',

	/* ---------------------------------------------------------- prices */
	'Prices &amp; payment': 'ფასები და გადახდა',
	'Clear prices. Flexible payment.': 'გამჭვირვალე ფასები. მოქნილი გადახდა.',
	'Every flat shows its price online, updated live. No calls needed to find out how much it costs.':
		'თითოეულ ბინას ფასი ონლაინ აწერია და რეალურ დროში ახლდება. ფასის გასაგებად დარეკვა საჭირო არ არის.',
	'Option one': 'პირველი ვარიანტი',
	'Full payment': 'სრული გადახდა',
	'Pay in full at signing and take <b><span data-v="discountFull">5</span>% off</b> the listed price.':
		'გადაიხადეთ სრულად ხელშეკრულების გაფორმებისას და მიიღეთ <b><span data-v="discountFull"></span>% ფასდაკლება</b> მითითებულ ფასზე.',
	'Option two': 'მეორე ვარიანტი',
	'Developer instalment': 'დეველოპერის განვადება',
	'<b><span data-v="downPct">30</span>% down</b>, the rest over <b><span data-v="months">24</span> months</b> at <b>0%</b> interest. Arranged in our own sales office, no bank involved.':
		'<b><span data-v="downPct"></span>% პირველადი შენატანი</b>, დანარჩენი <b><span data-v="months"></span> თვეში</b>, <b>0%</b> პროცენტით. ფორმდება ჩვენსავე გაყიდვების ოფისში, ბანკის გარეშე.',
	'Option three': 'მესამე ვარიანტი',
	'Mortgage': 'იპოთეკა',
	'With our partner banks. We help with the paperwork.':
		'ჩვენს პარტნიორ ბანკებთან. დოკუმენტაციაში დაგეხმარებით.',
	'Calculator': 'კალკულატორი',
	'See your monthly payment': 'გაიგეთ ყოველთვიური გადასახადი',
	'Flat price': 'ბინის ფასი',
	'Down payment': 'პირველადი შენატანი',
	'Term': 'ვადა',
	'Monthly payment': 'ყოველთვიური გადასახადი',
	'Developer instalment at 0% interest.<br> <span id="c-note"></span>':
		'დეველოპერის განვადება 0% პროცენტით.<br> <span id="c-note"></span>',
	'Only <b><span data-v="available">17</span> ready flats</b> left in <span data-v="project">Todria 11</span>':
		'<span data-v="project"></span>ში დარჩა სულ <b><span data-v="available"></span> მზა ბინა</b>',
	'Get the full price list': 'მიიღეთ სრული ფასების სია',

	/* --------------------------------------------------------- gallery */
	'Real photos &amp; video': 'რეალური ფოტო და ვიდეო',
	'Real photos. No renders.': 'რეალური ფოტოები. რენდერების გარეშე.',
	'Every image here was taken on site. Come and compare for yourself.':
		'ყველა ფოტო ადგილზეა გადაღებული. მობრძანდით და თავად შეადარეთ.',
	'Book a viewing — today or this weekend': 'დაჯავშნეთ ვიზიტი — დღესვე ან შაბათ-კვირას',

	/* ------------------------------------------------------- developer */
	'About the developer': 'დეველოპერის შესახებ',
	'LP Group: we finish what we start': 'ელპი ჯგუფი: რასაც ვიწყებთ, ვასრულებთ',
	'<span data-v="years">14</span> years in construction, <span data-v="delivered">9</span> buildings delivered, <span data-v="families">1,200</span> families already moved in. <span data-v="project">Todria 11</span> is the proof — finished and standing.':
		'<span data-v="years"></span> წელი მშენებლობაში, <span data-v="delivered"></span> ჩაბარებული კორპუსი, <span data-v="families"></span> უკვე შესახლებული ოჯახი. <span data-v="project"></span> ამის დადასტურებაა — დასრულებული და მდგარი.',
	'Years in construction': 'წელი მშენებლობაში',
	'Buildings delivered': 'ჩაბარებული კორპუსი',
	'Families moved in': 'შესახლებული ოჯახი',

	/* ------------------------------------------------------------- FAQ */
	'FAQ': 'კითხვები',
	'Questions buyers ask us': 'კითხვები, რომელსაც მყიდველები გვისვამენ',
	'Anything not here, a manager will answer on the phone in a minute.':
		'რაც აქ არ წერია, მენეჯერი ტელეფონით წუთში გიპასუხებთ.',
	'Call us': 'დაგვირეკეთ',
	'Can I move in right away?': 'შემიძლია თუ არა მაშინვე შესახლება?',
	'Yes. The building is finished. After signing and payment you get the keys.':
		'დიახ. შენობა დასრულებულია. ხელშეკრულების გაფორმებისა და გადახდის შემდეგ იღებთ გასაღებს.',
	'What condition are the flats in?': 'რა მდგომარეობაში გადაეცემა ბინები?',
	'White frame.': 'თეთრი კარკასი.',
	'Can I pay in instalments?': 'შესაძლებელია თუ არა განვადება?',
	'Yes: <span data-v="downPct">30</span>% down and the rest over <span data-v="months">24</span> months, at 0% interest.':
		'დიახ: <span data-v="downPct"></span>% პირველადი შენატანი და დანარჩენი <span data-v="months"></span> თვეში, 0% პროცენტით.',
	'Can I use a mortgage?': 'შემიძლია თუ არა იპოთეკით შეძენა?',
	'Yes, with <span data-v="banksLine">our partner banks</span>. Our manager helps with the documents.':
		'დიახ, <span data-v="banksLine"></span>-თან. ჩვენი მენეჯერი დოკუმენტაციაში დაგეხმარებათ.',
	'Is there parking?': 'არის თუ არა პარკინგი?',
	'Yes — underground, sold separately.': 'დიახ — მიწისქვეშა, იყიდება ცალკე.',
	'Can foreigners buy?': 'შეუძლიათ თუ არა უცხოელებს შეძენა?',
	'Yes, foreigners can own apartments in Georgia. We guide you through the process.':
		'დიახ, უცხო ქვეყნის მოქალაქეებს საქართველოში ბინის ფლობა შეუძლიათ. პროცესში სრულად გაგიწევთ თანხლებას.',
	'How do I see the flat?': 'როგორ ვნახო ბინა?',
	'Book a viewing and a manager will meet you on site.':
		'დაჯავშნეთ ვიზიტი და მენეჯერი ადგილზე დაგხვდებათ.',

	/* -------------------------------------------------------- contacts */
	'Come see your future home this week': 'მობრძანდით და ნახეთ თქვენი მომავალი სახლი ამ კვირაში',
	'Leave your number. A manager will call within <span data-v="callbackMinutes">15</span> minutes, send the price list and book a time that suits you.':
		'დატოვეთ ნომერი. მენეჯერი დაგირეკავთ <span data-v="callbackMinutes"></span> წუთში, გამოგიგზავნით ფასების სიას და დაჯავშნის თქვენთვის მოსახერხებელ დროს.',
	'Viewings seven days a week, at the hour that suits you.':
		'ვიზიტები კვირაში შვიდივე დღე, თქვენთვის მოსახერხებელ საათზე.',
	'The full price list, with every flat still available.':
		'სრული ფასების სია ყველა თავისუფალი ბინით.',
	'No pressure — walk the building and decide after.':
		'ზეწოლის გარეშე — დაათვალიერეთ კორპუსი და შემდეგ გადაწყვიტეთ.',
	'Name': 'სახელი',
	'Phone': 'ტელეფონი',
	'Flat you liked': 'ბინა, რომელიც მოგეწონათ',
	'Book my viewing': 'დამიჯავშნეთ ვიზიტი',
	'<svg width="15" height="15"><use href="#i-lock"></use></svg>We never share your number.':
		'<svg width="15" height="15"><use href="#i-lock"></use></svg>თქვენს ნომერს არავის გადავცემთ.',
	'Thank you!': 'გმადლობთ!',
	'We\'ll call you within <span data-v="callbackMinutes">15</span> minutes.':
		'დაგირეკავთ <span data-v="callbackMinutes"></span> წუთში.',

	/* ---------------------------------------------------------- footer */
	'LP Group': 'ელპი ჯგუფი',
	'A finished residential building in <span data-v="district">Todria</span>, <span data-v="city">Rustavi</span>. Keys right after purchase.':
		'დასრულებული საცხოვრებელი კორპუსი <span data-v="district"></span>ში, <span data-v="city"></span>. გასაღები შეძენისთანავე.',
	'Sales office': 'გაყიდვების ოფისი',
	'The project': 'პროექტი',
	'Available flats': 'თავისუფალი ბინები',
	'Follow': 'გამოგვყევით',
	'Facebook': 'Facebook',
	'The render, in detail': 'რენდერი დეტალურად',
	'Rendered live with three.js on WebGPU.': 'რეალურ დროში დარენდერებულია three.js-ით WebGPU-ზე.',

	/* -------------------------------------------- what the pointer hears */
	'LP Group, home': 'ელპი ჯგუფი, მთავარი',
	'Sections': 'სექციები',
	'Menu': 'მენიუ',
	'The flats to the left': 'ბინები მარცხნივ',
	'The flats to the right': 'ბინები მარჯვნივ',
	'The room before': 'წინა ოთახი',
	'The next room': 'შემდეგი ოთახი',
	'The show flat, opened from above': 'საჩვენებელი ბინა, ზემოდან გახსნილი',
	'Your name': 'თქვენი სახელი',
	'Close': 'დახურვა',

	/* ------------------------------------------ the facts, from content.js
	 * `fill()` puts these on the page, so they are looked up by their own
	 * English rather than by the markup around them. Numbers, prices and
	 * URLs have no entry and fall through unchanged. */
	'Todria 11': 'თოდრია 11',
	'Todria': 'თოდრია',
	'Rustavi': 'რუსთავი',
	'Tbilisi': 'თბილისი',
	'Todria St. 11, Rustavi': 'თოდრიას ქ. 11, რუსთავი',
	'Mon–Sat, 10:00–19:00': 'ორშ–შაბ, 10:00–19:00',
	'Right after purchase': 'შეძენისთანავე',
	'Monolithic reinforced-concrete frame': 'მონოლითური რკინაბეტონის კარკასი',
	'100 mm mineral-wool facade insulation': 'ფასადის 100 მმ მინერალბამბის თბოიზოლაცია',
	'REHAU double-glazed windows': 'REHAU-ს ორმაგი შემინვის ფანჯრები',
	'a balcony in every flat': 'აივანი ყველა ბინაში',
	'white frame': 'თეთრი კარკასი',
	/* One line each side on purpose: an object KEY cannot be built out of
	 * two string literals and a plus, which is how the rest of this file
	 * would have wrapped it. */
	'White frame: plastered walls, screed floors, wiring and plumbing brought to every room, glazed windows and a steel entrance door. Ready for your own finish.':
		'თეთრი კარკასი: შელესილი კედლები, მოჭიმული იატაკი, ყველა ოთახში შეყვანილი ელექტროგაყვანილობა და სანტექნიკა, შემინული ფანჯრები და რკინის კარი. მზადაა თქვენი რემონტისთვის.',
	'Yes - underground, 48 spaces, sold separately.': 'დიახ — მიწისქვეშა, 48 ადგილი, იყიდება ცალკე.',
	'Pharmacy and a grocery': 'აფთიაქი და სასურსათო მაღაზია',
	'School': 'სკოლა',
	'Kindergarten': 'საბავშვო ბაღი',
	'Bus stop': 'ავტობუსის გაჩერება',
	'Supermarket': 'სუპერმარკეტი',
	'Park': 'პარკი',
	'Clinic': 'კლინიკა',
	'TBC Bank': 'თიბისი ბანკი',
	'Bank of Georgia': 'საქართველოს ბანკი',
	'Liberty Bank': 'ლიბერთი ბანკი',
	'1-bedroom': '1-ოთახიანი',
	'2-bedroom': '2-ოთახიანი',
	'3-bedroom': '3-ოთახიანი',
	'Street, south-west': 'ქუჩისკენ, სამხრეთ-დასავლეთი',
	'Courtyard, east': 'ეზოსკენ, აღმოსავლეთი',
	'Street, north': 'ქუჩისკენ, ჩრდილოეთი',
	'Courtyard, west': 'ეზოსკენ, დასავლეთი',

	/* ------------------------------------------- what the page builds
	 * Templates, not sentences: `{n}` is a number and Georgian is free to
	 * put it wherever it belongs. See `tf`. */
	'Floor {n}': 'სართული {n}',
	'Floor': 'სართული',
	'{free} of {all} free': '{all}-დან {free} თავისუფალი',
	'from': 'დან',
	'{n} on the street line · all taken': '{n} ქუჩის მხარეს · ყველა დაკავებულია',
	'Look inside the ': 'შეიხედეთ — ',
	'{n} flats': '{n} ბინა',
	'{n} floors': '{n} სართული',
	'{n} on this floor': '{n} ამ სართულზე',
	'from {price} · {n} free': '{price}-დან · {n} თავისუფალი',
	'none left on this floor': 'ამ სართულზე აღარ არის',
	'flat {n}': 'ბინა {n}',
	'The show flat · ': 'საჩვენებელი ბინა · ',
	'floor {n}': 'სართული {n}',
	'{label}, {area} m²': '{label}, {area} მ²',
	'Floor ': 'სართული ',
	'{n} room': '{n} ოთახი',
	'Flat {n} · {label} · {area} m² · {price}': 'ბინა {n} · {label} · {area} მ² · {price}',
	'<b>{n}</b> flat matches': 'შეესაბამება <b>{n}</b> ბინა',
	'<b>{n}</b> flats match': 'შეესაბამება <b>{n}</b> ბინა',
	'{n} available now': '{n} ხელმისაწვდომია',
	'None left — ask about the next release': 'აღარ არის — იკითხეთ შემდეგი ეტაპი',
	'Licensed developer': 'ლიცენზირებული დეველოპერი',
	'Notary partner': 'პარტნიორი ნოტარიუსი',
	'Ask what else is free': 'იკითხეთ, რა არის თავისუფალი',
	'{n} months': '{n} თვე',
	'{down} down, {rest} over {n} months.': '{down} პირველადი შენატანი, დანარჩენი {rest} — {n} თვეში.',
	'{n} of {all}': '{all}-დან {n}',
	'Please tell us your name.': 'გთხოვთ, მიუთითოთ სახელი.',
	'A phone number we can call back on.': 'ტელეფონის ნომერი, რომელზეც დაგირეკავთ.',

	/* the flat card's own rows, and the three statuses */
	'Available': 'თავისუფალი',
	'Reserved': 'დაჯავშნილი',
	'Sold': 'გაყიდული',
	'Aspect': 'ხედი',
	'Balcony': 'აივანი',
	'Condition': 'მდგომარეობა',
	'Yes': 'დიახ',
	'No': 'არა',

	/* the rooms of the show flat, as app.js names them */
	'Kitchen & dining': 'სამზარეულო და სასადილო',
	'Master bedroom': 'საძინებელი',
	'Bedroom 2': 'მეორე საძინებელი',
	'Bathroom': 'სველი წერტილი',
	'Hall': 'ჰოლი',
	'Living balcony': 'მისაღების აივანი',
	'Bedroom balcony': 'საძინებლის აივანი',

	'Pick a flat on the left and its plan, aspect and price appear here. Everything green can be seen on site today.':
		'აირჩიეთ ბინა მარცხნივ და აქ გამოჩნდება მისი გეგმა, ხედი და ფასი. ყველა მწვანე ბინის ნახვა დღესვე შეგიძლიათ ადგილზე.',

	/* the gallery's own tabs, which are the keys of SITE.gallery */
	'Facade': 'ფასადი',
	'Lobby': 'ჰოლი',
	'Courtyard': 'ეზო',
	'Flats': 'ბინები',
	'Views': 'ხედები',
	'Video': 'ვიდეო',
};

/* ===================================================================== *
 *  Putting it on the page.
 * ===================================================================== */

const SKIP = new Set( [ 'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE' ] );
const ATTRS = [ 'aria-label', 'placeholder', 'alt', 'title' ];
const norm = ( s ) => s.replace( /\s+/g, ' ' ).trim();

/* The English, kept on the node the first time it is touched. Switching
 * back is a restore and not a second dictionary - so a round trip through
 * Georgian and out again lands on exactly the markup index.html shipped,
 * including whatever `fill()` had already put in it. */
const ORIG = new WeakMap();
const ORIG_ATTR = new WeakMap();

let LANG = DEFAULT_LANG;
export const lang = () => LANG;

/* Every element with text of its own, which is the unit a translation is
 * written for. Its subtree belongs to it, so nothing is translated twice,
 * and an element whose text is a FACT is left for `fill()`. */
function units( root, out ) {
	if ( root.nodeType !== 1 || SKIP.has( root.tagName ) ) return out;
	if ( root.id === 'boot' || root.namespaceURI !== 'http://www.w3.org/1999/xhtml' ) return out;
	if ( ! root.hasAttribute( 'data-v' ) ) {
		const own = [ ...root.childNodes ].some(
			c => c.nodeType === 3 && /\S/.test( c.textContent ) );
		if ( own ) { out.push( root ); return out; }
	}
	for ( const c of root.children ) units( c, out );
	return out;
}

/* The title face, over whatever the DESIGN already sets in capitals.
 * Marks rather than rewrites - the text is never touched - so it is
 * idempotent and costs nothing to run again over a region the page has
 * just rebuilt. The mark goes on the outermost such element: everything
 * under it inherits both the face and the capitals. */
export function applyTitleFont( root = document.body ) {
	const on = LANG === 'ka';
	const walk = ( n ) => {
		if ( n.nodeType !== 1 || SKIP.has( n.tagName ) ) return;
		if ( getComputedStyle( n ).textTransform === 'uppercase' ) {
			n.classList.toggle( 'mtav', on );
			return;
		}
		n.classList.remove( 'mtav' );
		for ( const c of n.children ) walk( c );
	};
	walk( root );
}

/* One string, for the parts of the page that are built rather than
 * written - the flat cards, the counts, the scene's own room names. */
export const t = ( en ) => ( LANG === 'ka' && KA[ en ] ) || en;

/* Swap the whole document. Returns true if anything changed, so the
 * caller knows whether the facts need dropping in again. */
export function applyLang( next, root = document.body ) {
	const to = LANGS.includes( next ) ? next : DEFAULT_LANG;
	LANG = to;
	document.documentElement.lang = to;
	document.documentElement.dataset.lang = to;

	for ( const n of units( root, [] ) ) {
		if ( ! ORIG.has( n ) ) ORIG.set( n, norm( n.innerHTML ) );
		const en = ORIG.get( n );
		const ka = KA[ en ];
		const want = to === 'ka' && ka ? ka : en;
		if ( norm( n.innerHTML ) !== want ) n.innerHTML = want;
	}
	for ( const n of root.querySelectorAll( '[' + ATTRS.join( '],[' ) + ']' ) ) {
		if ( ! ORIG_ATTR.has( n ) ) {
			const keep = {};
			for ( const a of ATTRS ) if ( n.hasAttribute( a ) ) keep[ a ] = n.getAttribute( a );
			ORIG_ATTR.set( n, keep );
		}
		const keep = ORIG_ATTR.get( n );
		for ( const a of Object.keys( keep ) ) {
			const ka = KA[ keep[ a ] ];
			n.setAttribute( a, to === 'ka' && ka ? ka : keep[ a ] );
		}
	}
	return to;
}

/* The tab and the search result, which are not in the body. */
const HEAD_KA = {
	title: 'ელპი ჯგუფი — შენობა მზადაა, თქვენი ბინა გელოდებათ',
	description: 'ელპი ჯგუფის დასრულებული საცხოვრებელი კორპუსი რუსთავში. '
		+ 'აირჩიეთ ბინა ონლაინ, დაათვალიერეთ 3D-ში და მიიღეთ გასაღები შეძენისთანავე.',
};
let HEAD_EN = null;
export function applyHead( to ) {
	const meta = document.querySelector( 'meta[name="description"]' );
	if ( ! HEAD_EN ) HEAD_EN = { title: document.title,
		description: meta ? meta.content : '' };
	const src = to === 'ka' ? HEAD_KA : HEAD_EN;
	document.title = src.title;
	if ( meta ) meta.content = src.description;
}

/* What the visitor last chose, or Georgian - this is a building in
 * Rustavi and its buyers are local. `?lang=en` overrides both, which is
 * what the shot rigs use. */
export function startLang() {
	const q = new URLSearchParams( location.search ).get( 'lang' );
	if ( LANGS.includes( q ) ) return q;
	try {
		const kept = localStorage.getItem( 'lp:lang' );
		if ( LANGS.includes( kept ) ) return kept;
	} catch ( e ) { /* private window: the default is fine */ }
	return DEFAULT_LANG;
}

export function keepLang( to ) {
	try { localStorage.setItem( 'lp:lang', to ); } catch ( e ) { /* nothing to do */ }
}

/* A template with slots, for the strings the page BUILDS: "Floor {n}",
 * "{free} of {all} free". The words cannot be translated one at a time
 * and left in English order, and the numbers are not translatable at
 * all, so the whole template is the key and Georgian moves the slots
 * wherever it needs them. */
export const tf = ( en, vars ) =>
	t( en ).replace( /\{(\w+)\}/g, ( _, k ) => vars[ k ] != null ? vars[ k ] : '' );
