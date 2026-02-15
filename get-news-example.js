const axios = require('axios');
const moment = require('moment');
const fs = require('fs');

// Start measuring time
const startTime = Date.now();

// User configuration (countries)
const usa = true;
const canada = true;  // You can set to true to include more countries
const giappone = true;
const germania = true;
const francia = true;
const svizzera = true;
const australia = true;
const nuovaZelanda = true;

// Set the choice to fetch data for today
const useYesterday = false;
const startHour = 0; // Start at midnight to cover the entire day

// Date setup using moment.js
const today = moment().startOf('day');
const startDate = useYesterday ? today.subtract(1, 'days') : today;
const startTimeOfDay = startDate.clone().add(startHour, 'hours');
const endTimeOfDay = startDate.clone().add(23, 'hours').add(59, 'minutes');

// Country selection map
const countriesSelection = {
    'US': usa,
    'CA': canada,
    'JP': giappone,
    'DE': germania,
    'FR': francia,
    'CH': svizzera,
    'AU': australia,
    'NZ': nuovaZelanda
};

// Filter selected countries
const countries = Object.keys(countriesSelection).filter(country => countriesSelection[country]);

// URL and headers for the API request
const url = 'https://economic-calendar.tradingview.com/events';
const headers = {
    'Origin': 'https://in.tradingview.com'
};

// Payload (request parameters) to fetch medium and high importance news for today
const payload = {
    from: startTimeOfDay.toISOString(),
    to: endTimeOfDay.toISOString(),
    countries: countries.join(','),
    minImportance: 0  // Fetch medium (0) and high (+1) importance news items
};

// Making the request using axios
axios.get(url, { headers, params: payload })
    .then(response => {
        const data = response.data.result;

        // Save the data to a JSON file
        fs.writeFile('economic_events.json', JSON.stringify(data, null, 2), (err) => {
            if (err) {
                console.error('Error writing to file', err);
            } else {
                console.log('Data saved to economic_events.json');
            }
        });

        // End measuring time
        const endTime = Date.now();
        const executionTime = (endTime - startTime) / 1000; // Convert milliseconds to seconds
        console.log(`Execution time: ${executionTime.toFixed(2)} seconds`);
    })
    .catch(error => {
        console.error('Error fetching data:', error);
    });
