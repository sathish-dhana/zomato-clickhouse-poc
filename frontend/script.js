// Global variables
let logsChart = null;
const API_BASE_URL = "http://127.0.0.1:7000"; // Update port to 7000
let isLoadingStats = false; // Flag to prevent multiple simultaneous stat loading
let currentPage = 1;
let pageSize = 10;
let allLogs = []; // Store all logs for client-side pagination

// Initialize the page when the DOM is ready
$(document).ready(function() {
    // Setup date range picker
    initDateRangePicker();
    
    // Load environments dropdown
    loadEnvironments();
    
    // Set initial page size
    pageSize = parseInt($('#page-size').val());
    
    // Load initial logs and stats
    loadLogs();
    loadStats();
    
    // Set up event listeners
    $('#filter-form button').on('click', function(e) {
        e.preventDefault();
        loadLogs();
        loadStats();
    });
    
    // Add page size change listener
    $('#page-size').on('change', function() {
        pageSize = parseInt($(this).val());
        currentPage = 1; // Reset to first page
        displayLogs(); // Refresh the display with new page size
    });
});

// Initialize the date range picker
function initDateRangePicker() {
    const start = moment().subtract(7, 'days');
    const end = moment();
    
    $('#date-range').daterangepicker({
        startDate: start,
        endDate: end,
        ranges: {
           'Last Hour': [moment().subtract(1, 'hours'), moment()],
           'Today': [moment().startOf('day'), moment()],
           'Yesterday': [moment().subtract(1, 'days').startOf('day'), moment().subtract(1, 'days').endOf('day')],
           'Last 7 Days': [moment().subtract(6, 'days'), moment()],
           'Last 30 Days': [moment().subtract(29, 'days'), moment()],
           'This Month': [moment().startOf('month'), moment().endOf('month')],
           'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')]
        }
    });
}

// Load available environments from the API
function loadEnvironments() {
    $.ajax({
        url: API_BASE_URL + '/api/environments',
        method: 'GET',
        success: function(environments) {
            const dropdown = $('#environment');
            environments.forEach(env => {
                dropdown.append(`<option value="${env}">${env}</option>`);
            });
        },
        error: function(err) {
            console.error('Error loading environments:', err);
        }
    });
}

// Load logs based on current filters
function loadLogs() {
    // Show loading indicator
    $('#logs-table-body').empty();
    $('#loading').removeClass('d-none');
    $('#no-logs').addClass('d-none');
    
    // Get filter values
    const dateRange = $('#date-range').val().split(' - ');
    const startDate = moment(dateRange[0], 'MM/DD/YYYY').format('YYYY-MM-DD');
    const endDate = moment(dateRange[1], 'MM/DD/YYYY').format('YYYY-MM-DD');
    const environment = $('#environment').val();
    const searchTerm = $('#search-term').val();
    
    // Make API request with explicit limit
    $.ajax({
        url: API_BASE_URL + '/api/logs',
        method: 'GET',
        data: {
            start_date: startDate,
            end_date: endDate,
            env: environment,
            search_term: searchTerm,
            limit: 100 // Explicitly set limit to 100
        },
        success: function(logs) {
            // Hide loading indicator
            $('#loading').addClass('d-none');
            
            // Store all logs for pagination
            allLogs = logs.slice(0, 100);
            
            // Reset to first page
            currentPage = 1;
            
            // Display logs with pagination
            displayLogs();
        },
        error: function(err) {
            $('#loading').addClass('d-none');
            console.error('Error loading logs:', err);
            alert('Failed to load logs. Please try again.');
        }
    });
    
    // Remove any auto-refresh or infinite scroll functionality
    if (window.autoRefreshTimer) {
        clearInterval(window.autoRefreshTimer);
        window.autoRefreshTimer = null;
    }
}

// Display logs with pagination
function displayLogs() {
    // Clear the table
    $('#logs-table-body').empty();
    
    // Calculate pagination
    const total = allLogs.length;
    const totalPages = Math.ceil(total / pageSize);
    
    // Ensure current page is valid
    if (currentPage < 1) currentPage = 1;
    if (currentPage > totalPages) currentPage = totalPages;
    
    // Calculate slice indices
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, total);
    
    // Update pagination info
    $('#total-logs').text(total);
    $('#page-start').text(total > 0 ? startIndex + 1 : 0);
    $('#page-end').text(endIndex);
    $('#log-count').text(`${total} logs`);
    
    // Show no logs message if needed
    if (total === 0) {
        $('#no-logs').removeClass('d-none');
        // Clear pagination
        $('#pagination-controls').empty();
        return;
    }
    
    // Get logs for current page
    const logsToDisplay = allLogs.slice(startIndex, endIndex);
    
    // Populate table
    logsToDisplay.forEach(log => {
        const row = createLogRow(log);
        $('#logs-table-body').append(row);
    });
    
    // Add event listeners for the view details buttons
    $('.view-details-btn').on('click', function() {
        const logData = $(this).data('log');
        showLogDetails(logData);
    });
    
    // Update pagination controls
    updatePaginationControls(totalPages);
}

// Update pagination controls
function updatePaginationControls(totalPages) {
    const paginationElement = $('#pagination-controls');
    paginationElement.empty();
    
    // Don't show pagination if only one page
    if (totalPages <= 1) return;
    
    // Previous button
    paginationElement.append(`
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" data-page="${currentPage - 1}" aria-label="Previous">
                <span aria-hidden="true">&laquo;</span>
            </a>
        </li>
    `);
    
    // Page numbers
    const maxVisiblePages = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
    
    // Adjust start if we're near the end
    if (endPage - startPage + 1 < maxVisiblePages) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }
    
    // First page if not visible
    if (startPage > 1) {
        paginationElement.append(`
            <li class="page-item">
                <a class="page-link" href="#" data-page="1">1</a>
            </li>
        `);
        
        // Ellipsis if needed
        if (startPage > 2) {
            paginationElement.append(`
                <li class="page-item disabled">
                    <a class="page-link" href="#">...</a>
                </li>
            `);
        }
    }
    
    // Page numbers
    for (let i = startPage; i <= endPage; i++) {
        paginationElement.append(`
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" data-page="${i}">${i}</a>
            </li>
        `);
    }
    
    // Last page if not visible
    if (endPage < totalPages) {
        // Ellipsis if needed
        if (endPage < totalPages - 1) {
            paginationElement.append(`
                <li class="page-item disabled">
                    <a class="page-link" href="#">...</a>
                </li>
            `);
        }
        
        paginationElement.append(`
            <li class="page-item">
                <a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a>
            </li>
        `);
    }
    
    // Next button
    paginationElement.append(`
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" data-page="${currentPage + 1}" aria-label="Next">
                <span aria-hidden="true">&raquo;</span>
            </a>
        </li>
    `);
    
    // Add click handlers
    $('.page-link').on('click', function(e) {
        e.preventDefault();
        const page = $(this).data('page');
        if (page && page !== currentPage) {
            currentPage = page;
            displayLogs();
            // Scroll to top of table
            $('html, body').animate({
                scrollTop: $('#logs-table-body').offset().top - 100
            }, 200);
        }
    });
}

// Create a table row for a log entry
function createLogRow(log) {
    const envClass = log.env.toLowerCase();
    
    return `<tr>
        <td>${log.timestamp}</td>
        <td><span class="badge env-badge ${envClass}">${log.env}</span></td>
        <td>${log.container_id}</td>
        <td class="message-cell">${log.message}</td>
        <td>
            <button class="btn btn-sm btn-outline-primary view-details-btn" data-log='${JSON.stringify(log)}' data-bs-toggle="modal" data-bs-target="#log-details-modal">View Details</button>
        </td>
    </tr>`;
}

// Show the details of a log entry in the modal
function showLogDetails(log) {
    // Format the log data for display
    const formattedLog = JSON.stringify(log, null, 2);
    
    // Populate the modal
    $('#log-details-content').html(`
        <div class="log-details">
            <h6>Trace ID: ${log.trace_id}</h6>
            <h6>Message: ${log.message}</h6>
            <h6>Full Details:</h6>
            <pre>${formattedLog}</pre>
        </div>
    `);
}

// Load statistics
function loadStats() {
    // Prevent multiple simultaneous calls
    if (isLoadingStats) {
        return;
    }
    
    isLoadingStats = true;
    
    // Get filter values
    const dateRange = $('#date-range').val().split(' - ');
    const startDate = moment(dateRange[0], 'MM/DD/YYYY').format('YYYY-MM-DD');
    const endDate = moment(dateRange[1], 'MM/DD/YYYY').format('YYYY-MM-DD');
    
    // Make API request
    $.ajax({
        url: API_BASE_URL + '/api/stats',
        method: 'GET',
        data: {
            start_date: startDate,
            end_date: endDate
        },
        success: function(stats) {
            // Update environment stats
            updateEnvStats(stats.by_environment);
            
            // Update daily stats chart
            updateDailyStatsChart(stats.by_day);
            
            // Reset loading flag
            isLoadingStats = false;
        },
        error: function(err) {
            console.error('Error loading stats:', err);
            isLoadingStats = false;
        }
    });
}

// Update the environment statistics display
function updateEnvStats(envStats) {
    const container = $('#env-stats');
    container.empty();
    
    if (envStats.length === 0) {
        container.html('<p class="text-muted">No data available</p>');
        return;
    }
    
    // Get total count
    const totalCount = envStats.reduce((sum, item) => sum + item.count, 0);
    
    // Add each environment stat
    envStats.forEach(stat => {
        const percentage = Math.round((stat.count / totalCount) * 100);
        const envClass = stat.env.toLowerCase();
        
        container.append(`
            <div class="stats-item">
                <div class="stats-label">
                    <span class="badge env-badge ${envClass} me-2">${stat.env}</span>
                </div>
                <div class="stats-value">
                    ${stat.count} (${percentage}%)
                </div>
            </div>
        `);
    });
}

// Update the daily statistics chart
function updateDailyStatsChart(dayStats) {
    // Clear any existing chart to prevent memory leaks and data accumulation
    const canvas = document.getElementById('logs-by-day');
    const ctx = canvas.getContext('2d');
    
    // Destroy previous chart instance if it exists
    if (logsChart) {
        logsChart.destroy();
        logsChart = null;
    }
    
    // Clear the canvas completely
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (!dayStats || dayStats.length === 0) {
        // Show "No data" message if no stats
        ctx.textAlign = 'center';
        ctx.fillStyle = '#888';
        ctx.font = '14px Arial';
        ctx.fillText('No data available', canvas.width / 2, canvas.height / 2);
        return;
    }
    
    // Limit to maximum 7 days of data to prevent excessive chart growth
    const recentStats = dayStats.slice(-7);
    const labels = recentStats.map(item => item.day);
    const data = recentStats.map(item => item.count);
    
    // Create a new chart instance with fixed configuration
    logsChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Log Count',
                data: data,
                backgroundColor: 'rgba(54, 162, 235, 0.2)',
                borderColor: 'rgba(54, 162, 235, 1)',
                borderWidth: 1,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 500 // Shorter animation
            },
            layout: {
                padding: {
                    left: 10,
                    right: 10,
                    top: 0,
                    bottom: 0
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 0 // Use integers only
                    },
                    grid: {
                        drawBorder: false
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    enabled: true
                }
            }
        }
    });
} 